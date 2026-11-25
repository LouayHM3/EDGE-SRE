import io
import urllib.request

URL = "https://zenodo.org/api/records/18937117/files/LO2v2-metrics.zip/content"
SIZE = 1_317_357_774

class RemoteMetrics(io.RawIOBase):
    def __init__(self, url=URL, size=SIZE):
        self.url = url
        self.size = size
        self.position = 0
        self.start = 0
        self.buffer = b""

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        base = (0, self.position, self.size)[whence]
        self.position = base + offset
        return self.position

    def read(self, size=-1):
        stop = self.size if size < 0 else min(self.position + size, self.size)
        if stop <= self.position:
            return b""
        if not (self.start <= self.position and stop <= self.start + len(self.buffer)):
            end = min(max(stop, self.position + 65536), self.size) - 1
            request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.position}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                expected = f"bytes {self.position}-{end}/{self.size}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise OSError(f"Unexpected response for {expected}")
                data = response.read()
                if len(data) != end - self.position + 1:
                    raise OSError(f"Incomplete response for {expected}")
                self.buffer = data
            self.start = self.position
        data = self.buffer[self.position - self.start:stop - self.start]
        self.position = stop
        return data
