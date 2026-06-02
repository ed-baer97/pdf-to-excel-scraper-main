/**
 * POST /admin/exports → poll status → redirect to download.
 * data-export-kind on button; data-export-params JSON object optional.
 */
(function () {
  function pollExport(jobId, statusUrl, onDone, onError) {
    fetch(statusUrl, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data.success) {
          onError(data.error || "status failed");
          return;
        }
        if (data.status === "done" && data.download_url) {
          onDone(data.download_url);
          return;
        }
        if (data.status === "failed") {
          onError(data.error || "export failed");
          return;
        }
        setTimeout(function () {
          pollExport(jobId, statusUrl, onDone, onError);
        }, 2000);
      })
      .catch(function (e) {
        onError(String(e));
      });
  }

  function startExport(btn) {
    var kind = btn.getAttribute("data-export-kind");
    if (!kind) return;
    var params = {};
    try {
      var raw = btn.getAttribute("data-export-params");
      if (raw) params = JSON.parse(raw);
    } catch (e) {
      /* ignore */
    }
    params.export_kind = kind;
    btn.disabled = true;
    var label = btn.innerHTML;
    btn.innerHTML = btn.getAttribute("data-busy-label") || "…";
    fetch("/admin/exports", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (!data.success) {
          throw new Error(data.error || "create failed");
        }
        pollExport(
          data.job_id,
          data.status_url,
          function (url) {
            window.location.href = url;
          },
          function (err) {
            alert(err);
            btn.disabled = false;
            btn.innerHTML = label;
          }
        );
      })
      .catch(function (err) {
        alert(err);
        btn.disabled = false;
        btn.innerHTML = label;
      });
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-export-kind]");
    if (!btn || btn.tagName !== "BUTTON") return;
    if (btn.getAttribute("data-export-sync") === "1") return;
    ev.preventDefault();
    startExport(btn);
  });
})();
