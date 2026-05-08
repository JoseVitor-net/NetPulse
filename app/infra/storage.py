"""
Storage — Camada de persistência completa do NetPulse.

Responsabilidades:
- Criar e manter o schema SQLite (4 tabelas)
- Persistir pings em batch (BATCH_SIZE por host antes de flush)
- Persistir snapshots de stats ao final de cada sessão por host
- Persistir alerts gerados pelo NetworkAnalyzer
- Expor API de leitura para o histórico na UI

Design:
- Escrita em batch: elimina I/O síncrono por pacote (problema do database.py legado)
- Thread-safety: chamado exclusivamente da main thread via signal/slot do PingManager
- Conexão aberta/fechada por operação (sqlite3 com context manager)
- Sem dependências de Qt

Schema:
    sessions        — uma entrada por execução de monitoramento
    pings           — registros brutos por host e sessão
    stats_snapshots — métricas agregadas ao fim de cada host
    alerts          — alertas gerados pelo NetworkAnalyzer
"""
import json
import os
import sqlite3
from datetime import datetime
from loguru import logger

from app.core.models import Alert, PingResult, PingStats

DB_PATH = "data/netpulse.db"
BATCH_SIZE = 10  # Flush para o banco a cada N pings por host


class Storage:
    """Repositório SQLite com escrita em batch e API de leitura para histórico."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Buffer de escrita: host → list[tuple] de pings pendentes
        self._ping_buffer: dict[str, list[tuple]] = {}
        # session_id corrente (definido pelo SessionManager via set_session)
        self._session_id: str | None = None

        self._init_schema()

    # ─────────────────────────────────────────────────────────────
    # Configuração de Sessão
    # ─────────────────────────────────────────────────────────────

    def set_session(self, session_id: str) -> None:
        """Define a sessão ativa. Chamado pelo PingManager no início de cada sessão."""
        self._session_id = session_id
        self._ping_buffer.clear()

    # ─────────────────────────────────────────────────────────────
    # Escrita (chamadas do PingManager)
    # ─────────────────────────────────────────────────────────────

    def buffer_ping(self, result: PingResult) -> None:
        """
        Acumula um resultado de ping no buffer em memória.
        Faz flush automático quando o buffer do host atinge BATCH_SIZE.
        Nunca lança exceção para o caller.
        """
        if not self._session_id:
            return

        host = result.host
        if host not in self._ping_buffer:
            self._ping_buffer[host] = []

        self._ping_buffer[host].append((
            self._session_id,
            host,
            result.latency_ms,
            result.timestamp.isoformat(),
            int(result.success),
            result.error_msg,
        ))

        if len(self._ping_buffer[host]) >= BATCH_SIZE:
            self._flush_host(host)

    def flush_host(self, host: str) -> None:
        """Força flush do buffer de um host específico (chamado ao fim do worker)."""
        self._flush_host(host)

    def flush_all(self) -> None:
        """Força flush de todos os buffers pendentes (chamado ao stop_session)."""
        for host in list(self._ping_buffer.keys()):
            self._flush_host(host)

    def save_alert(self, alert: Alert) -> None:
        """Persiste um alerta gerado pelo NetworkAnalyzer."""
        if not self._session_id:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT INTO alerts
                       (session_id, host, severity, kind, message, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        self._session_id,
                        alert.host,
                        alert.severity,
                        alert.kind,
                        alert.message,
                        alert.timestamp.isoformat(),
                    ),
                )
        except Exception as e:
            logger.error(f"[Storage] Erro ao salvar alert: {e}")

    def save_stats_snapshot(self, stats: PingStats) -> None:
        """Persiste snapshot de métricas agregadas de um host ao fim da sessão."""
        if not self._session_id:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT INTO stats_snapshots
                       (session_id, host, avg_latency, min_latency,
                        max_latency, packet_loss, std_dev, mos, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._session_id,
                        stats.host,
                        stats.avg_latency,
                        stats.min_latency,
                        stats.max_latency,
                        stats.packet_loss,
                        stats.std_dev,
                        stats.mos,
                        datetime.now().isoformat(),
                    ),
                )
        except Exception as e:
            logger.error(f"[Storage] Erro ao salvar stats snapshot: {e}")

    # ─────────────────────────────────────────────────────────────
    # API de Leitura (chamadas da UI via PingManager / HistoryPanel)
    # ─────────────────────────────────────────────────────────────

    def list_sessions(
        self,
        host_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Lista sessões com filtros opcionais.
        Cada dict: {session_id, started_at, ended_at, hosts, ping_count}
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                clauses: list[str] = []
                params: list = []

                if host_filter:
                    clauses.append("s.hosts LIKE ?")
                    params.append(f"%{host_filter}%")
                if date_from:
                    clauses.append("s.started_at >= ?")
                    params.append(date_from)
                if date_to:
                    clauses.append("s.started_at <= ?")
                    params.append(date_to + "T23:59:59")

                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params.append(limit)

                rows = conn.execute(
                    f"""SELECT s.session_id, s.started_at, s.ended_at, s.hosts,
                               COUNT(p.id) AS ping_count
                        FROM sessions s
                        LEFT JOIN pings p ON p.session_id = s.session_id
                        {where}
                        GROUP BY s.session_id
                        ORDER BY s.started_at DESC
                        LIMIT ?""",
                    params,
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Storage] Erro ao listar sessões: {e}")
            return []

    # Alias de retrocompatibilidade para código legado
    def get_sessions(self, limit: int = 20) -> list[dict]:
        return self.list_sessions(limit=limit)

    def get_session_summary(self, session_id: str) -> dict:
        """
        Resumo agregado de uma sessão inteira.
        Retorna: {session_id, started_at, ended_at, hosts, total_pings,
                  total_losses, avg_latency, min_latency, max_latency,
                  avg_mos, avg_std_dev, alert_count}
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row

                sess = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if not sess:
                    return {}

                p = conn.execute(
                    """SELECT COUNT(*) AS total,
                              SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS losses,
                              AVG(latency_ms) AS avg_lat,
                              MIN(latency_ms) AS min_lat,
                              MAX(latency_ms) AS max_lat
                       FROM pings WHERE session_id = ?""",
                    (session_id,),
                ).fetchone()

                sn = conn.execute(
                    """SELECT AVG(mos) AS avg_mos, AVG(std_dev) AS avg_std
                       FROM stats_snapshots WHERE session_id = ?""",
                    (session_id,),
                ).fetchone()

                ac = conn.execute(
                    "SELECT COUNT(*) FROM alerts WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]

            hosts_raw = sess["hosts"]
            return {
                "session_id": sess["session_id"],
                "started_at": sess["started_at"],
                "ended_at": sess["ended_at"],
                "hosts": json.loads(hosts_raw) if hosts_raw else [],
                "total_pings": p["total"] or 0,
                "total_losses": p["losses"] or 0,
                "avg_latency": round(p["avg_lat"] or 0.0, 2),
                "min_latency": round(p["min_lat"] or 0.0, 2),
                "max_latency": round(p["max_lat"] or 0.0, 2),
                "avg_mos": round(sn["avg_mos"] or 0.0, 2),
                "avg_std_dev": round(sn["avg_std"] or 0.0, 2),
                "alert_count": ac,
            }
        except Exception as e:
            logger.error(f"[Storage] Erro ao buscar summary: {e}")
            return {}

    def get_session_results(
        self, session_id: str, host: str | None = None
    ) -> list[dict]:
        """
        Todos os pings de uma sessão, opcionalmente filtrados por host.
        Cada dict: {host, latency_ms, timestamp, success, error_msg}
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                if host:
                    rows = conn.execute(
                        """SELECT host, latency_ms, timestamp, success, error_msg
                           FROM pings WHERE session_id=? AND host=?
                           ORDER BY timestamp ASC""",
                        (session_id, host),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT host, latency_ms, timestamp, success, error_msg
                           FROM pings WHERE session_id=?
                           ORDER BY timestamp ASC""",
                        (session_id,),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Storage] Erro ao buscar resultados: {e}")
            return []

    def get_session_hosts(self, session_id: str) -> list[str]:
        """Retorna os hosts monitorados numa sessão."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT hosts FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[Storage] Erro ao buscar hosts da sessão: {e}")
        return []

    def get_session_pings(self, session_id: str, host: str) -> list[dict]:
        """Alias retrocompat: retorna pings de um host numa sessão."""
        return self.get_session_results(session_id, host)

    def get_session_stats(self, session_id: str) -> list[dict]:
        """
        Retorna snapshots de stats de todos os hosts de uma sessão.
        Cada dict: {host, avg_latency, min_latency, max_latency, packet_loss}
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT host, avg_latency, min_latency, max_latency,
                              packet_loss, std_dev, mos, timestamp
                       FROM stats_snapshots
                       WHERE session_id = ?
                       ORDER BY timestamp DESC""",
                    (session_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Storage] Erro ao buscar stats: {e}")
            return []

    def get_session_alerts(self, session_id: str) -> list[dict]:
        """
        Retorna todos os alertas de uma sessão.
        Cada dict: {host, severity, kind, message, timestamp}
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT host, severity, kind, message, timestamp
                       FROM alerts
                       WHERE session_id = ?
                       ORDER BY timestamp DESC""",
                    (session_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Storage] Erro ao buscar alertas: {e}")
            return []

    # ─────────────────────────────────────────────────────────────
    # Gerenciamento de Sessão (chamado pelo SessionManager)
    # ─────────────────────────────────────────────────────────────

    def create_session(self, session_id: str, hosts: list[str]) -> None:
        """Registra o início de uma nova sessão no banco."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT INTO sessions (session_id, started_at, hosts)
                       VALUES (?, ?, ?)""",
                    (session_id, datetime.now().isoformat(), json.dumps(hosts)),
                )
            logger.info(f"[Storage] Sessão criada: {session_id}")
        except Exception as e:
            logger.error(f"[Storage] Erro ao criar sessão: {e}")

    def close_session(self, session_id: str) -> None:
        """Registra o fim de uma sessão."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE sessions SET ended_at = ? WHERE session_id = ?",
                    (datetime.now().isoformat(), session_id),
                )
        except Exception as e:
            logger.error(f"[Storage] Erro ao fechar sessão: {e}")

    # ─────────────────────────────────────────────────────────────
    # Internos
    # ─────────────────────────────────────────────────────────────

    def _flush_host(self, host: str) -> None:
        """Escreve todos os pings pendentes de um host em um único INSERT batch."""
        rows = self._ping_buffer.pop(host, [])
        if not rows:
            return
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executemany(
                    """INSERT INTO pings
                       (session_id, host, latency_ms, timestamp, success, error_msg)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            logger.debug(f"[Storage] Flush: {len(rows)} pings de '{host}' gravados.")
        except Exception as e:
            logger.error(f"[Storage] Erro no flush de '{host}': {e}")

    def _init_schema(self) -> None:
        """Cria as tabelas caso não existam. Idempotente."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        ended_at   TEXT,
                        hosts      TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS pings (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        host       TEXT NOT NULL,
                        latency_ms REAL,
                        timestamp  TEXT NOT NULL,
                        success    INTEGER NOT NULL,
                        error_msg  TEXT,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );

                    CREATE TABLE IF NOT EXISTS stats_snapshots (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT NOT NULL,
                        host        TEXT NOT NULL,
                        avg_latency REAL,
                        min_latency REAL,
                        max_latency REAL,
                        packet_loss REAL,
                        std_dev     REAL DEFAULT 0.0,
                        mos         REAL DEFAULT 0.0,
                        timestamp   TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );

                    CREATE TABLE IF NOT EXISTS alerts (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        host       TEXT NOT NULL,
                        severity   TEXT NOT NULL,
                        kind       TEXT NOT NULL,
                        message    TEXT NOT NULL,
                        timestamp  TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_pings_session_host
                        ON pings(session_id, host);
                    CREATE INDEX IF NOT EXISTS idx_alerts_session
                        ON alerts(session_id);
                """)
            logger.info("[Storage] Schema inicializado.")
            
            # Migração de retrocompatibilidade
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("ALTER TABLE stats_snapshots ADD COLUMN std_dev REAL DEFAULT 0.0")
                    conn.execute("ALTER TABLE stats_snapshots ADD COLUMN mos REAL DEFAULT 0.0")
                logger.info("[Storage] Migração do schema v0.3 aplicada (std_dev, mos).")
            except sqlite3.OperationalError:
                pass # Colunas já existem
                
        except Exception as e:
            logger.error(f"[Storage] Erro ao inicializar schema: {e}")
