"""Run and optionally verify the portable Windows monitoring stack."""

import argparse
from base64 import b64encode
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml


def wait_for(url, processes, check=lambda data: True):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A monitoring service exited; inspect the logs in the run directory")
        try:
            with urlopen(url, timeout=5) as reply:
                data = json.load(reply)
            if check(data):
                return data
        except (URLError, json.JSONDecodeError):
            pass
        time.sleep(0.75)
    raise TimeoutError(f"Monitoring endpoint did not become ready: {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Verify dashboard and scraping, then exit")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--prometheus-port", type=int, default=9090)
    parser.add_argument("--grafana-port", type=int, default=3000)
    args = parser.parse_args()
    tools = Path(sys.prefix) / "tools"
    prometheus = next(tools.glob("prometheus-3.5.0*/prometheus.exe"), None)
    grafana = next(tools.glob("grafana*/bin/grafana.exe"), None)
    if prometheus is None or grafana is None:
        raise SystemExit("Extract the Windows Prometheus and Grafana distributions into .venv/tools")

    directory = Path("results", f"monitoring-{uuid4().hex[:10]}").resolve()
    directory.mkdir(parents=True)
    for name in ("grafana-data", "grafana-logs", "grafana-plugins"):
        (directory / name).mkdir()
    print(f"Local service logs: {directory}", flush=True)
    api_url = f"http://127.0.0.1:{args.api_port}"
    prom_url = f"http://127.0.0.1:{args.prometheus_port}"
    grafana_url = f"http://127.0.0.1:{args.grafana_port}"

    prometheus_config = yaml.safe_load(Path("monitoring/prometheus.yml").read_text())
    prometheus_config["scrape_configs"][0]["static_configs"][0]["targets"] = [f"127.0.0.1:{args.api_port}"]
    prom_file = directory / "prometheus.yml"
    prom_file.write_text(yaml.safe_dump(prometheus_config), encoding="utf-8")
    provision = directory / "provisioning"
    for kind in ("datasources", "dashboards", "alerting", "plugins"):
        (provision / kind).mkdir(parents=True)
    source = Path("monitoring/grafana/provisioning/datasources/prometheus.yml")
    configuration = yaml.safe_load(source.read_text())
    configuration["datasources"][0]["url"] = prom_url
    (provision / "datasources" / source.name).write_text(yaml.safe_dump(configuration), encoding="utf-8")

    processes = []
    with ExitStack() as stack:
        def start(name, command, env=None):
            output = stack.enter_context((directory / f"{name}.log").open("w", encoding="utf-8"))
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, env=env)
            processes.append(process)

            def stop():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)

            stack.callback(stop)

        start("api", [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1",
                      "--port", str(args.api_port)])
        start("prometheus", [str(prometheus), f"--config.file={prom_file}",
                             f"--storage.tsdb.path={directory / 'prometheus-data'}",
                             f"--web.listen-address=127.0.0.1:{args.prometheus_port}"])
        home = grafana.parent.parent
        password = uuid4().hex
        start("grafana", [str(grafana), "server", "--homepath", str(home)], env={
            **os.environ,
            "GF_SERVER_HTTP_ADDR": "127.0.0.1", "GF_SERVER_HTTP_PORT": str(args.grafana_port),
            "GF_PATHS_DATA": str(directory / "grafana-data"),
            "GF_PATHS_LOGS": str(directory / "grafana-logs"),
            "GF_PATHS_PLUGINS": str(directory / "grafana-plugins"),
            "GF_PATHS_PROVISIONING": str(provision),
            "GF_AUTH_ANONYMOUS_ENABLED": "true",
            "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
            "GF_SECURITY_ADMIN_PASSWORD": password,
            "GF_PLUGINS_PREINSTALL_DISABLED": "true",
            "GF_ANALYTICS_REPORTING_ENABLED": "false",
            "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
            "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES": "false",
        })
        health = wait_for(api_url + "/health", processes)
        target = "/api/v1/query?query=cloudpulse_replay_alerts"
        has_samples = lambda payload: bool(payload.get("data", {}).get("result"))
        direct = wait_for(prom_url + target, processes, has_samples)
        wait_for(grafana_url + "/api/health", processes, lambda data: data.get("database") == "ok")
        # The API import avoids Windows path canonicalization during Grafana file provisioning.
        payload = json.loads(Path("monitoring/grafana/dashboards/cloudpulse.json").read_text())
        auth = b64encode(f"admin:{password}".encode()).decode()
        request = Request(
            grafana_url + "/api/dashboards/db",
            data=json.dumps({"dashboard": payload, "overwrite": True}).encode(),
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as reply:
            assert json.load(reply)["status"] == "success"
        dashboard = wait_for(grafana_url + "/api/dashboards/uid/cloudpulse-local", processes)
        through_grafana = wait_for(
            grafana_url + "/api/datasources/proxy/uid/cloudpulse-prometheus" + target, processes, has_samples,
        )
        expected = json.loads(Path("results/streaming_summary.json").read_text())["alerts"]
        assert float(direct["data"]["result"][0]["value"][1]) == expected
        assert float(through_grafana["data"]["result"][0]["value"][1]) == expected
        assert len(dashboard["dashboard"]["panels"]) == 7
        summary = {
            "model_version": health["model_version"], "prometheus_scrape": True,
            "grafana_datasource_query": True, "grafana_panels": 7, "simulated_alerts": expected,
            "run_directory": directory.relative_to(Path.cwd()).as_posix(),
        }
        Path("results/monitoring_validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2), flush=True)
        if not args.verify:
            print(grafana_url + "/d/cloudpulse-local", flush=True)
            try:
                while all(process.poll() is None for process in processes):
                    time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
