import os


class CsvLogger:
    """Append-only CSV logger with a running line count (no full-file rescan needed to
    check the trim threshold) and an O(n)-time, O(1)-memory trim (streams the file
    twice instead of loading it into a Python list, unlike the old cleanup_csv())."""

    def __init__(self, filename, fields, max_lines, trim_slack=500):
        self.filename = filename
        self.fields = fields
        self.max_lines = max_lines
        self.trim_slack = trim_slack
        self._ensure_file()
        self.line_count = self._count_existing_lines()

    def _header(self):
        return ",".join(self.fields)

    def _ensure_file(self):
        try:
            with open(self.filename, "r"):
                pass
        except OSError:
            with open(self.filename, "w") as f:
                f.write(self._header() + "\n")

    def _count_existing_lines(self):
        try:
            with open(self.filename, "r") as f:
                f.readline()  # header
                return sum(1 for _ in f)
        except OSError:
            return 0

    def write_row(self, values):
        row = ",".join(str(values.get(field, "")) for field in self.fields)
        with open(self.filename, "a") as f:
            f.write(row + "\n")
        self.line_count += 1
        if self.line_count > self.max_lines + self.trim_slack:
            self._trim()

    def _trim(self):
        skip = max(0, self.line_count - self.max_lines)
        tmp_filename = self.filename + ".tmp"
        with open(self.filename, "r") as src, open(tmp_filename, "w") as dst:
            dst.write(src.readline())  # header
            for i, line in enumerate(src):
                if i >= skip:
                    dst.write(line)
        os.remove(self.filename)
        os.rename(tmp_filename, self.filename)
        self.line_count = self.max_lines
        print(f"CSV auf {self.max_lines} Zeilen gekuerzt")

    def stat(self):
        try:
            size = os.stat(self.filename)[6]
        except OSError:
            size = 0
        return {"lines": self.line_count, "size_bytes": size}
