import socket
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger
from ping3 import ping

from app.core.models import PingResult
from app.infra.database import DatabaseSetup

class PingService(QThread):
    result_received = pyqtSignal(PingResult)
    finished = pyqtSignal()

    def __init__(self, host: str, count: int = 4, timeout: int = 1000, continuous: bool = False, db: DatabaseSetup = None):
        """
        Inicializa o serviço de ping assíncrono.
        :param host: O endereço IP ou domínio alvo.
        :param count: Quantidade de pacotes a enviar (se não contínuo).
        :param timeout: Tempo limite em milissegundos.
        :param continuous: Se True, faz ping indefinidamente até stop() ser chamado.
        :param db: Instância opcional de DatabaseSetup para persistência local.
        """
        super().__init__()
        self.host = host
        self.count = count
        # ping3 espera o tempo limite em segundos
        self.timeout_sec = timeout / 1000.0
        self.continuous = continuous
        self.is_running = True
        self.db = db

    def run(self):
        logger.info(f"Iniciando monitoramento de rede via ICMP (ping3) para: {self.host}")
        
        # Pré-resolução de DNS (Tratamento para hostnames inválidos logo de cara)
        try:
            resolved_ip = socket.gethostbyname(self.host)
            logger.info(f"Hostname resolvido para IP: {resolved_ip}")
        except socket.gaierror as e:
            logger.error(f"Falha de DNS: {e}")
            err_result = PingResult(host=self.host, timestamp=datetime.now(), success=False, error_msg="DNS Resolution Failed")
            self.result_received.emit(err_result)
            self.finished.emit()
            return
        
        while self.is_running:
            timestamp = datetime.now()
            try:
                # Dispara o ICMP e aguarda o retorno da latência em segundos
                # Usa o IP resolvido para evitar lookup repetido a cada pacote
                delay_sec = ping(resolved_ip, timeout=self.timeout_sec)
                
                if delay_sec is None:
                    # Pacote perdido / Esgotado o tempo limite (Timeout)
                    result = PingResult(host=self.host, timestamp=timestamp, success=False, error_msg="Timeout")
                elif delay_sec is False:
                    # Falha na resolução do host / Inalcançável (Unreachable)
                    result = PingResult(host=self.host, timestamp=timestamp, success=False, error_msg="Host Unreachable")
                else:
                    # Sucesso: Converte de segundos para milissegundos
                    latency_ms = delay_sec * 1000.0
                    result = PingResult(host=self.host, timestamp=timestamp, success=True, latency_ms=latency_ms)

                # Persiste em banco de dados, se habilitado
                if self.db:
                    self.db.save_result(result)

                # Emite o sinal para a UI atualizar o Dashboard
                self.result_received.emit(result)

                if not self.continuous:
                    self.count -= 1
                    if self.count <= 0:
                        break

                # Sleep de 1 segundo (1000ms) para não sobrecarregar a rede
                self.msleep(1000)

            except PermissionError as e:
                # O Windows geralmente permite sockets raw, mas Linux/Mac podem exigir root/sudo
                logger.error(f"Erro de permissão ICMP (execute como Administrador/Root): {e}")
                err_result = PingResult(host=self.host, timestamp=timestamp, success=False, error_msg="Permission Denied")
                self.result_received.emit(err_result)
                break
            except Exception as e:
                logger.error(f"Exceção inesperada no ping: {e}")
                err_result = PingResult(host=self.host, timestamp=timestamp, success=False, error_msg=str(e))
                self.result_received.emit(err_result)
                break

        logger.info(f"Monitoramento encerrado para: {self.host}")
        self.finished.emit()

    def stop(self):
        """Interrompe a execução contínua com segurança."""
        self.is_running = False
