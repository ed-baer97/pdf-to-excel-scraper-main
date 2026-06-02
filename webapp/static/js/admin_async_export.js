/**
 * POST /admin/exports → poll status → download when ready.
 * Attach to a button via data-async-export="analytics" and optional data-export-params JSON.
 */
(function () {
  function pollStatus(statusUrl, onDone, onError) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(statusUrl, { credentials: "same-origin" });
        const data = await res.json();
        if (!data.success) {
          clearInterval(interval);
          onError(data.error || "status failed");
          return;
        }
        if (data.status === "done" && data.download_url) {
          clearInterval(interval);
          onDone(data.download_url);
          return;
        }
        if (data.status === "failed") {
          clearInterval(interval);
          onError(data.error || "export failed");
        }
      } catch (e) {
        clearInterval(interval);
        onError(String(e));
      }
    }, 2000);
  }

  window.startAdminAsyncExport = function (exportKind, params, options) {
    const opts = options || {};
    const btn = opts.button;
    const prevText = btn ? btn.innerHTML : null;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML =
        opts.loadingText ||
        '<span class="spinner-border spinner-border-sm me-1"></span>Файл готовится…';
    }

    fetch("/admin/exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(Object.assign({ export_kind: exportKind }, params || {})),
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.success || !data.status_url) {
          throw new Error(data.error || "create export failed");
        }
        pollStatus(
          data.status_url,
          (url) => {
            if (btn) {
              btn.disabled = false;
              if (prevText !== null) btn.innerHTML = prevText;
            }
            window.location.href = url;
          },
          (err) => {
            if (btn) {
              btn.disabled = false;
              if (prevText !== null) btn.innerHTML = prevText;
            }
            alert(err);
          }
        );
      })
      .catch((err) => {
        if (btn) {
          btn.disabled = false;
          if (prevText !== null) btn.innerHTML = prevText;
        }
        alert(String(err));
      });
  };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-async-export]").forEach((el) => {
      el.addEventListener("click", function (ev) {
        if (el.getAttribute("data-sync") === "1" || ev.shiftKey) {
          return;
        }
        ev.preventDefault();
        let params = {};
        const raw = el.getAttribute("data-export-params");
        if (raw) {
          try {
            params = JSON.parse(raw);
          } catch (_) {
            /* ignore */
          }
        }
        const kind = el.getAttribute("data-async-export");
        if (!kind) return;
        if (el.tagName === "A" && !params.period_number) {
          const u = new URL(el.href, window.location.origin);
          u.searchParams.forEach((v, k) => {
            params[k] = v;
          });
        }
        startAdminAsyncExport(kind, params, { button: el });
      });
    });
  });
})();
