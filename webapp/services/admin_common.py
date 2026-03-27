"""Common helpers used by admin views."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import redirect, request


def is_safe_redirect_url(target: str) -> bool:
    """Allow only same-host or local redirects."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target)
    if not test.scheme and not test.netloc:
        return target.startswith("/")
    return test.scheme in ("http", "https") and test.netloc == ref.netloc


def redirect_back(fallback_url: str):
    """Return user to next_url/referrer when safe; else fallback."""
    next_url = (
        request.form.get("next_url")
        or request.args.get("next_url")
        or request.referrer
    )
    if next_url and is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(fallback_url)


def apply_analytics_filters(
    subjects_data_sor,
    subjects_data_soch,
    subjects_data_grades,
    filter_subject,
    filter_class,
    filter_teacher,
):
    """Apply subject/class/teacher filters to analytics payload maps."""

    def _filter_item(item):
        if filter_class and item.get("class_name") != filter_class:
            return False
        if filter_teacher and (item.get("teacher") or "").strip() != filter_teacher:
            return False
        return True

    def _filter_dict(data_dict):
        result = {}
        for subj, items in data_dict.items():
            if filter_subject and subj != filter_subject:
                continue
            filtered = [i for i in items if _filter_item(i)]
            if filtered:
                result[subj] = filtered
        return result

    return (
        _filter_dict(subjects_data_sor),
        _filter_dict(subjects_data_soch),
        _filter_dict(subjects_data_grades),
    )
