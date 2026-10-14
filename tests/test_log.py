"""The log file beside the data, and the diagnostics text built from it.
(What the diagnostics say about accounts is checked in test_health.py.)"""

from ariadne import config
from ariadne import log as log_svc


def test_reports_land_in_the_log_file(app):
    path = log_svc.path()
    assert path == config.APP_DIR / "ariadne.log" and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "[start] Ariadne" in text and "data in" in text       # create_app wrote the start line
    log_svc.log.warning("[test] something to find")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log_svc.log.exception("[test] with a traceback")
    text = path.read_text(encoding="utf-8")
    assert " W [test] something to find" in text
    assert "RuntimeError: boom" in text                         # the traceback is in the file
    assert log_svc.tail(2).splitlines()[-1] == "RuntimeError: boom"


def test_diagnostics_text_and_log_download(client):
    res = client.get("/api/system/diagnostics").json
    text = res["text"]
    assert text.startswith("Ariadne ") and "Python " in text
    assert f"Data dir: {config.paths.data_dir}" in text
    assert "Images indexed: 0" in text and "Updates: latest unknown" in text
    assert "--- last 150 log lines ---" in text and "[start] Ariadne" in text
    assert res["log_path"] == str(log_svc.path())

    res = client.get("/api/system/diagnostics?download=1")
    assert res.mimetype == "text/plain" and "ariadne-diagnostics.txt" in res.headers["Content-Disposition"]
    assert res.data.decode("utf-8").startswith("Ariadne ")

    res = client.get("/api/system/log")
    assert res.status_code == 200 and res.mimetype == "text/plain"
    assert b"[start] Ariadne" in res.data
    assert client.get("/api/system").json["log_path"] == str(log_svc.path())


def test_bug_report_prefills_a_github_issue(client):
    """Settings' "Report a bug": what the user typed plus the diagnostics,
    as a new-issue address for the public repository, and as a file."""
    from urllib.parse import parse_qs, urlsplit

    res = client.get("/api/system/report?summary=The%20grid%20froze%0Aafter%20a%20sort"
                     "&steps=Sorted%20by%20name").json
    assert res["title"] == "The grid froze"
    body = res["body"]
    assert "**What went wrong**\nThe grid froze\nafter a sort" in body
    assert "**What I did just before**\nSorted by name" in body
    assert "<details><summary>Diagnostics</summary>" in body and "Images indexed: 0" in body
    parts = urlsplit(res["url"])
    assert parts.netloc == "github.com" and parts.path == f"/{config.UPDATE_REPO}/issues/new"
    query = parse_qs(parts.query)
    assert query["title"] == ["The grid froze"] and query["body"] == [body] and query["labels"] == ["bug"]
    assert len(res["url"]) <= 6500 and res["cut"] is False
    assert res["text"].startswith("The grid froze\n\nWhat went wrong:\nThe grid froze")
    assert "--- last 150 log lines ---" in res["text"]

    # without the diagnostics only the versions go along
    lean = client.get("/api/system/report?summary=x&diagnostics=0").json
    assert "Diagnostics" not in lean["body"] and "Ariadne " in lean["body"]
    assert "Images indexed" not in lean["text"]

    # a log too long for an address: the prefilled body loses the older
    # lines, the newest stay, and the file keeps them all
    for i in range(400):
        log_svc.log.info(f"[test] filler line {i} " + "x" * 60)
    res = client.get("/api/system/report?summary=long").json
    assert res["cut"] is True and len(res["url"]) <= 6500
    assert "older log lines left out here" in res["body"] and "filler line 399" in res["body"]
    assert "filler line 300" in res["text"] and "filler line 300" not in res["body"]

    # nothing typed is still a report; the file download
    assert client.get("/api/system/report").json["title"] == "Bug report"
    res = client.get("/api/system/report?summary=x&download=1")
    assert res.mimetype == "text/plain" and "ariadne-report.txt" in res.headers["Content-Disposition"]
    assert res.data.decode("utf-8").startswith("x\n\nWhat went wrong:\nx")
