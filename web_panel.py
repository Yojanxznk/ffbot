# web_panel.py
from flask import Flask, render_template, jsonify, request
import database as db
import os
from datetime import datetime

app = Flask(__name__)

# ---------- PÁGINAS ----------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/accounts")
def accounts_page():
    return render_template("accounts.html")

@app.route("/logs")
def logs_page():
    return render_template("logs.html")

# ---------- API ----------
@app.route("/api/stats")
def api_stats():
    """Estadísticas calculadas respetando bot_enabled."""
    try:
        conn = db.get_conn()
        total = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
        online = conn.execute(
            "SELECT COUNT(*) c FROM accounts WHERE bot_enabled=1 AND status IN ('online','searching','playing')"
        ).fetchone()["c"]
        playing = conn.execute(
            "SELECT COUNT(*) c FROM accounts WHERE bot_enabled=1 AND status='playing'"
        ).fetchone()["c"]
        total_matches = conn.execute(
            "SELECT COALESCE(SUM(matches_played),0) c FROM accounts"
        ).fetchone()["c"]
        avg_level = conn.execute(
            "SELECT COALESCE(AVG(level),0) c FROM accounts"
        ).fetchone()["c"]
        conn.close()
        return jsonify({
            "total_accounts": total,
            "online": online,
            "playing": playing,
            "total_matches": total_matches,
            "avg_level": round(avg_level, 2),
        })
    except Exception:
        return jsonify(db.get_stats())


@app.route("/api/accounts")
def api_accounts():
    """Lista de cuentas con estado saneado.
    - bot_enabled=0                        -> forzar 'offline'
    - bot_enabled=1 y last_seen viejo      -> forzar 'offline' (bot muerto)
    - bot_enabled=1 y status vacío/offline -> 'searching'
    - resto de estados se respetan"""
    accounts = db.get_all_accounts()
    now = datetime.now()
    STALE_SECONDS = 60  # si last_seen es mayor a esto, el bot está muerto

    for a in accounts:
        bot_on = int(a.get("bot_enabled") or 0) == 1
        if not bot_on:
            a["status"] = "offline"
            continue

        # Verificar si el bot sigue vivo (last_seen reciente)
        last_seen = a.get("last_seen")
        is_stale = True
        if last_seen:
            try:
                ls = datetime.fromisoformat(last_seen)
                if (now - ls).total_seconds() < STALE_SECONDS:
                    is_stale = False
            except Exception:
                pass

        if is_stale:
            # Bot muerto -> offline aunque en DB diga otra cosa
            a["status"] = "offline"
        elif a.get("status") in (None, "", "offline", "idle"):
            a["status"] = "searching"

    return jsonify(accounts)


@app.route("/api/account/<uid>")
def api_account(uid):
    acc = db.get_account_by_uid(uid)
    if not acc:
        return jsonify({"ok": False, "msg": "no existe"}), 404
    return jsonify(acc)


@app.route("/api/account/<uid>/credentials")
def api_account_credentials(uid):
    """Devuelve UID y password de una cuenta (para el panel)."""
    acc = db.get_account_by_uid(uid)
    if not acc:
        return jsonify({"ok": False, "msg": "no existe"}), 404
    return jsonify({
        "ok": True,
        "uid": acc.get("uid"),
        "password": acc.get("password", ""),
        "nickname": acc.get("nickname", ""),
        "region": acc.get("region", ""),
    })


@app.route("/api/account/<uid>/status")
def api_account_status(uid):
    acc = db.get_account_by_uid(uid)
    if not acc:
        return jsonify({"ok": False, "msg": "no existe"}), 404
    return jsonify({
        "ok": True,
        "uid": uid,
        "status": acc.get("status"),
        "bot_enabled": int(acc.get("bot_enabled") or 0),
        "matches_played": acc.get("matches_played"),
        "last_seen": acc.get("last_seen"),
        "last_match_at": acc.get("last_match_at"),
    })


@app.route("/api/account/<uid>/progress")
def api_account_progress(uid):
    acc = db.get_account_by_uid(uid)
    if not acc:
        return jsonify({"ok": False, "msg": "no existe"}), 404
    target = int(acc.get("max_matches") or 0)
    done = int(acc.get("matches_played") or 0)
    pct = 0 if target <= 0 else min(100, round(done / target * 100))
    return jsonify({
        "ok": True,
        "uid": uid,
        "nickname": acc.get("nickname"),
        "level": acc.get("level"),
        "exp": acc.get("exp"),
        "region": acc.get("region"),
        "matches_played": done,
        "max_matches": target,
        "percent": pct,
        "status": acc.get("status"),
        "bot_enabled": int(acc.get("bot_enabled") or 0),
        "last_match_at": acc.get("last_match_at"),
    })


@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 200))
    uid = request.args.get("uid")
    return jsonify(db.get_logs(limit=limit, uid=uid))


@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    """Borra TODOS los logs de la DB."""
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM logs")
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/logs/clear/<uid>", methods=["POST"])
def api_clear_logs_uid(uid):
    """Borra los logs de una cuenta específica."""
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM logs WHERE account_uid=?", (str(uid),))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/matches/<uid>")
def api_matches(uid):
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM matches WHERE account_uid=? ORDER BY id DESC LIMIT 50",
            (str(uid),)
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception:
        return jsonify([])


@app.route("/api/account/add", methods=["POST"])
def api_add_account():
    uid = request.form.get("uid", "").strip()
    password = request.form.get("password", "").strip()
    region = request.form.get("region", "ME").strip().upper()
    max_matches = int(request.form.get("max_matches", 0) or 0)
    if not uid or not password:
        return jsonify({"ok": False, "msg": "UID y Password requeridos"}), 400
    try:
        conn = db.get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(uid, password, region, status, max_matches, bot_enabled, created_at) "
            "VALUES (?, ?, ?, 'offline', ?, 0, datetime('now'))",
            (uid, password, region, max_matches)
        )
        conn.commit()
        conn.close()
        db.add_log(uid, "success", f"Cuenta agregada (region={region}, meta={max_matches})")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/account/delete/<uid>", methods=["DELETE"])
def api_delete_account(uid):
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM accounts WHERE uid=?", (uid,))
        conn.commit()
        conn.close()
        db.add_log(uid, "warning", "Cuenta eliminada")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/account/<uid>/max_matches", methods=["POST"])
def api_set_max_matches(uid):
    try:
        max_matches = int(request.form.get("max_matches", 0))
    except Exception:
        return jsonify({"ok": False, "msg": "número inválido"}), 400
    ok = db.update_max_matches(uid, max_matches)
    if ok:
        db.add_log(uid, "info", f"Meta de partidas: {max_matches if max_matches>0 else '∞'}")
    return jsonify({"ok": ok})


@app.route("/api/account/<uid>/bot", methods=["POST"])
def api_set_bot_enabled(uid):
    enabled = request.form.get("enabled", "0") == "1"
    ok = db.set_bot_enabled(uid, enabled)
    if ok:
        if not enabled:
            try:
                conn = db.get_conn()
                conn.execute(
                    "UPDATE accounts SET status='offline', last_seen=? WHERE uid=?",
                    (datetime.now().isoformat(), str(uid))
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
        else:
            try:
                conn = db.get_conn()
                conn.execute(
                    "UPDATE accounts SET status='searching', last_seen=? WHERE uid=?",
                    (datetime.now().isoformat(), str(uid))
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
        db.add_log(uid, "info", f"Bot {'▶ activado' if enabled else '⏸ pausado'}")
    return jsonify({"ok": ok})


@app.route("/api/account/<uid>/reset", methods=["POST"])
def api_reset_matches(uid):
    try:
        conn = db.get_conn()
        conn.execute("UPDATE accounts SET matches_played=0, matches_won=0 WHERE uid=?", (uid,))
        conn.commit()
        conn.close()
        db.add_log(uid, "info", "Contador de partidas reiniciado")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


if __name__ == "__main__":
    db.init_db()
    print("=" * 60)
    print("   🎮 FF BOT PANEL")
    print("=" * 60)
    print("    Local:   http://127.0.0.1:8080")
    print("    Red LAN: http://<TU-IP-TERMUX>:8080")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)