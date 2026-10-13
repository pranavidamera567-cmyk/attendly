import csv
import io
from datetime import date, time

from flask import Response, jsonify, request

from .models import db


def bad(message, status=400):
    return jsonify(error=message), status


def parse_date(value, field="date"):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field}' must be a date like 2025-01-31")


def parse_time(value, field="time"):
    if value in (None, ""):
        return None
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field}' must be a time like 09:30")


def parse_month(value, today):
    """'YYYY-MM' -> (year, month); defaults to the current month."""
    if not value:
        return today.year, today.month
    try:
        y, m = value.split("-")
        y, m = int(y), int(m)
        if not 1 <= m <= 12:
            raise ValueError
        return y, m
    except ValueError:
        raise ValueError("'month' must look like 2025-01")


def paginate(query, serialise):
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))
    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return jsonify(items=[serialise(i) for i in items], total=total, page=page,
                   pages=max(1, -(-total // per_page)))


def _safe(cell):
    """Neutralise spreadsheet formula injection (cells starting with = + - @ are executed by Excel)."""
    if cell is None:
        return ""
    if not isinstance(cell, str):
        return cell
    return "'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def csv_response(filename, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(c) for c in r])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


def commit():
    db.session.commit()
