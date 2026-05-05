"""
SessionManager — Gerenciador de ciclo de vida de sessões de monitoramento.

Responsabilidades:
- Gerar session_id único (UUID4) por execução
- Registrar início e fim de sessão no Storage
- Expor o session_id corrente para o PingManager

Design:
- Puro Python. Sem Qt, sem rede.
- Stateful apenas quanto ao session_id ativo.
- Injetado no PingManager pelo Composition Root (main.py).
"""
import uuid
from loguru import logger

from app.infra.storage import Storage


class SessionManager:
    """Controlador de sessões de monitoramento com geração de UUID."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._current_id: str | None = None

    # ─────────────────────────────────────────────
    # API Pública
    # ─────────────────────────────────────────────

    def begin(self, hosts: list[str]) -> str:
        """
        Inicia uma nova sessão de monitoramento.
        Gera UUID, registra no banco e retorna o session_id.

        :param hosts: Lista de hosts que serão monitorados nessa sessão.
        :returns: session_id (UUID4 string)
        """
        self._current_id = str(uuid.uuid4())
        self._storage.create_session(self._current_id, hosts)
        self._storage.set_session(self._current_id)
        logger.info(f"[SessionManager] Sessão iniciada: {self._current_id}")
        return self._current_id

    def end(self) -> None:
        """Registra o fim da sessão ativa no banco."""
        if self._current_id:
            self._storage.close_session(self._current_id)
            logger.info(f"[SessionManager] Sessão encerrada: {self._current_id}")
            self._current_id = None

    @property
    def current_id(self) -> str | None:
        """Session ID da sessão ativa, ou None se não há sessão em andamento."""
        return self._current_id

    @property
    def is_active(self) -> bool:
        return self._current_id is not None
