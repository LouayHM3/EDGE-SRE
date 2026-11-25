"""Build the local Windows checkpoint adapter with Spark's Scala compiler."""

import os
from pathlib import Path
import subprocess
import sys

from spark import lo2_pipeline

LOCAL_JAR = Path(sys.prefix) / "tools" / "streaming-local-checkpoint.jar"


def build():
    source = Path(__file__).with_name("LocalCheckpointManager.scala")
    if LOCAL_JAR.exists() and LOCAL_JAR.stat().st_mtime >= source.stat().st_mtime:
        return LOCAL_JAR
    tools = Path(sys.prefix) / "tools"
    java = next(tools.glob("*/bin/java.exe"), None)
    if java is None:
        java = Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe"
    spark_home = os.environ.get("SPARK_HOME")
    jars = Path(spark_home) / "jars" if spark_home else Path(lo2_pipeline.__file__).parent
    if not spark_home:
        import pyspark
        jars = Path(pyspark.__file__).parent / "jars"
    LOCAL_JAR.parent.mkdir(parents=True, exist_ok=True)
    temp = LOCAL_JAR.with_name("streaming-local-checkpoint-build.jar")
    subprocess.run(
        [str(java), "-cp", str(jars / "*"), "scala.tools.nsc.Main", "-usejavacp",
         "-d", str(temp), str(source)],
        check=True, timeout=90,
    )
    temp.replace(LOCAL_JAR)
    return LOCAL_JAR
