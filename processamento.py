
from __future__ import annotations

from logs.logger_config import logger
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable
from comandos import WebController, DBClient

try:
    import oracledb
except Exception:
    oracledb = None

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


@runtime_checkable
class DatabaseProtocol(Protocol):
    def execute_query(
        self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]: ...

    def execute_scalar(
        self, sql: str, params: Optional[Tuple] = None) -> Any: ...

    def execute_non_query(
        self, sql: str, params: Optional[Tuple] = None) -> None: ...

    def call_procedure(self, name: str, params: Dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class BrowserProtocol(Protocol):
    def navegar(self, url: str) -> None: ...

    def aguardar_elemento_visivel(
        self, seletor: str, valor: str, timeout: int = 10) -> bool: ...

    def definir_valor(self, seletor: str, valor: str,
                      texto: str, timeout: int = 10) -> None: ...

    def click_elemento(self, seletor: str, valor: str,
                       timeout: int = 10) -> None: ...


@dataclass
class Config:
    caminho_padrao: Path
    dev_mode: bool
    db_user: str
    db_password: str
    db_host: str
    db_port: str
    db_service: str

    @classmethod
    def from_env(cls) -> "Config":
        caminho = os.environ.get(
            "CAMINHO_PADRAO", r"C:\IBMRPA\Hospital\Austa_RepasseMedico")
        dev = os.environ.get("DEV", "False").lower() in ("1", "true", "yes")
        user = os.environ.get("BD_USUARIO", "")
        pwd = os.environ.get("BD_SENHA", "")
        lista = os.environ.get("AUSTA_BD_ORACLE_DEV", "")
        host, port, service = ("", "", "")
        if lista:
            parts = lista.split(",")
            host = parts[0] if len(parts) > 0 else ""
            port = parts[1] if len(parts) > 1 else ""
            service = parts[2] if len(parts) > 2 else ""

        return cls(
            caminho_padrao=Path(caminho),
            dev_mode=dev,
            db_user=user,
            db_password=pwd,
            db_host=host,
            db_port=port,
            db_service=service,
        )


class Processamento:
    def __init__(self, config: Config, db: Optional[DatabaseProtocol] = None, browser: Optional[BrowserProtocol] = None) -> None:
        self.config = config
        self.db = db
        self.navegador = browser
        self._owns_db = db is None
        self._owns_browser = browser is None
        self.controle_execucao: Optional[int] = None

    def inicializar(self) -> None:
        logger.info("Inicializando automação")
        self.config.caminho_padrao.mkdir(parents=True, exist_ok=True)
        evidencia_dir = self.config.caminho_padrao / "Evidencia"
        evidencia_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp = now.strftime("%d.%m.%Y_%H.%M.%S")
        logger.debug("Data atual: %s -> %s", now.isoformat(), timestamp)

        if self.db is None:
            try:
                self.db = DBClient(self.config)  # type: ignore[assignment]
                logger.info("Conectado ao Oracle em %s:%s/%s", self.config.db_host,
                            self.config.db_port, self.config.db_service)
                self._owns_db = True
            except Exception as e:
                logger.exception("Falha ao conectar no Oracle: {e}")
                raise

        try:
            if self.db:
                cursor = self.db.cursor()

                # Cria variável para receber o valor de saída
                id_execucao_out = cursor.var(oracledb.NUMBER)

                params = {
                    "P_UNIDADE": os.environ.get("UNIDADE", ""),
                    "P_PROJETO": os.environ.get("PROJETO", ""),
                    "P_SCRIPT": os.environ.get("RPA_SCRIPT_NAME", ""),
                    "P_ETAPA": "-",
                    "P_USUARIO": os.environ.get("USERNAME", ""),
                    "P_ID_EXECUCAO": id_execucao_out  # variável OUT
                }

                try:
                    self.db.call_procedure(
                        "ROBO_RPA.PR_CRIAR_CONTROLE_EXECUCAO", params)

                    self.controle_execucao = id_execucao_out.getvalue()

                    logger.info(
                        f"Controle de execução criado com sucesso: {self.controle_execucao}")

                except Exception as e:
                    logger.exception(
                        f"Erro ao criar o controle de execução: {e}")
        except Exception:
            logger.exception("Erro ao registrar controle de execução")

    def registrar_log(self, tipo_log: str, mensagem: str, nr_repasse: Optional[str] = None) -> None:
        if self.config.dev_mode:
            if "INFO" in tipo_log.upper():
                logger.info(mensagem)
            elif "WARN" in tipo_log.upper():
                logger.warning(mensagem)
            else:
                logger.error(mensagem)

        if self.db:
            try:
                params = {"p_id_execucao": self.controle_execucao or 0, "p_tipo_log": tipo_log,
                          "p_registro_id": nr_repasse or "", "p_mensagem": mensagem}
                self.db.call_procedure("ROBO_RPA.PR_REGISTRAR_LOG", params)
            except Exception as e:
                logger.exception(f"Falha ao registrar log no banco: {e}")

    def login_tasy(self) -> bool:
        logger.info("Iniciando navegador Tasy")
        try:
            if self.navegador is None:
                self.navegador = WebController()
                self._owns_browser = True

            self.registrar_log("INFO", f"Login Tasy: True")
            return True
        except Exception:
            logger.exception("Falha no login Tasy")
            self.registrar_log("ERROR", "Login Tasy: False")
            return False

    def tasy_navegar_menu_telas(self, tela: str) -> None:
        if not self.navegador:
            raise RuntimeError("Navegador não iniciado")

        logger.info("Navegando para a tela: %s", tela)
        sucesso = self.navegador.aguardar_elemento_visivel(
            "xpath", "//input[@ng-model=\"search\"]", timeout=10)
        if not sucesso:
            raise RuntimeError("Campo de pesquisa do menu não encontrado")

        self.navegador.definir_valor(
            "xpath", "//input[@ng-model=\"search\"]", tela)
        encontrada = self.navegador.aguardar_elemento_visivel(
            "xpath", f"//span[text()='{tela}']", timeout=10)
        if not encontrada:
            raise AssertionError(f"Falha ao acessar o menu [{tela}]")

        self.navegador.click_elemento("xpath", f"//span[text()='{tela}']")

    def bd_importar_contas(self) -> int:
        if not self.db:
            raise RuntimeError("Banco não conectado")

        sql = (
            "SELECT cnpj, razao_social, seq_terceiro, nr_repasse, nr_titulo, dt_lib_titulo, email, dt_ult_envio_email, dt_lib_repasse "
            "FROM TASY.RPA_EMAIL_REPASSE_V "
            "WHERE DT_LIB_TITULO >= TO_DATE('01/09/2025', 'DD/MM/YYYY') "
            "ORDER BY DT_LIB_TITULO ASC"
        )
        rows = self.db.execute_query(sql)
        qtd_importados = 0

        for row in rows:
            cnpj = row.get("cnpj")
            razao_social = (row.get("razao_social") or "").replace("'", "\'")
            seq_terceiro = row.get("seq_terceiro")
            nr_repasse = row.get("nr_repasse")
            nr_titulo = row.get("nr_titulo")
            dt_lib_titulo = row.get("dt_lib_titulo")
            email = row.get("email")
            dt_ult_envio_email = row.get("dt_ult_envio_email")
            dt_lib_repasse = row.get("dt_lib_repasse")

            sql_check = "SELECT 1 FROM hos_repasse_medico WHERE nr_repasse = :1"
            existe = self.db.execute_scalar(sql_check, (nr_repasse,))
            if existe:
                continue

            sql_insert = (
                "INSERT INTO hos_repasse_medico (cnpj, razao_social, seq_terceiro, nr_repasse, nr_titulo, dt_lib_titulo, email, dt_ult_envio_email, status, dt_lib_repasse) "
                "VALUES (:1, :2, :3, :4, :5, TO_DATE(:6, 'DD/MM/YYYY HH24:MI:SS'), :7, SYSDATE, 'P', TO_DATE(:8, 'DD/MM/YYYY HH24:MI:SS'))"
            )
            params = (cnpj, razao_social, seq_terceiro, nr_repasse,
                      nr_titulo, dt_lib_titulo, email, dt_lib_repasse)
            try:
                self.db.execute_non_query(sql_insert, params)
                qtd_importados += 1
                self.registrar_log(
                    "INFO", f"Inserido na tabela HOS_REPASSE_MEDICO: Terceiro: {seq_terceiro} - Repasse: {nr_repasse} - Título: {nr_titulo} - CNPJ: {cnpj} - Status: P", nr_repasse)
            except Exception:
                logger.exception("Falha ao inserir repasse %s", nr_repasse)

        self.registrar_log(
            "INFO", f"Dados Importados com Sucesso: [{qtd_importados}/{len(rows)}]")
        return qtd_importados

    def executar(self) -> None:
        if not self.db:
            raise RuntimeError("Banco não conectado")

        self.registrar_log(
            "INFO", f"Inicio robô - Id Exec: {self.controle_execucao}")

        tabela = self.db.execute_query(
            "select * from hos_repasse_medico where status = 'P'")
        if not tabela:
            self.registrar_log("INFO", "Sem repasses para realizar o envio")
            return

        if not self.login_tasy():
            logger.error("Não foi possível efetuar login no Tasy")
            return

        self.tasy_navegar_menu_telas("Repasse para Terceiros")

        for idx, row in enumerate(tabela, start=1):
            cnpj = row.get("cnpj")
            razao_social = row.get("razao_social")
            seq_terceiro = row.get("seq_terceiro")
            nr_repasse = row.get("nr_repasse")
            nr_titulo = row.get("nr_titulo")
            dt_lib_titulo = row.get("dt_lib_titulo")
            email = row.get("email")
            dt_ult_envio_email = row.get("dt_ult_envio_email")
            dt_lib_repasse = row.get("dt_lib_repasse")

            if not (dt_lib_titulo and nr_titulo and email and dt_lib_repasse):
                status = "I"
                status_msg = (
                    f"Dados não preenchidos. Email: {email} - Dt Liberação: {dt_lib_titulo} - Nr Titulo: {nr_titulo} - Dt lib Repasse: {dt_lib_repasse}")
                self.registrar_log("INFO", status_msg)
                self.db.execute_non_query(
                    "Update hos_repasse_medico set status = :1, mensagem = :2 where nr_repasse = :3", (status, status_msg, nr_repasse))
                continue

            try:
                nav = self.navegador
                if not nav:
                    raise RuntimeError("Navegador não iniciado")

                nav.aguardar_elemento_visivel(
                    "xpath", "//div[@class=\"token-filter-container ng-scope\"]/tasy-wlabel", timeout=10)
                nav.click_elemento(
                    "xpath", "//div[@class=\"token-filter-container ng-scope\"]/tasy-wlabel")

                nav.aguardar_elemento_visivel(
                    "xpath", "//div[@class=\"filter-modal-content\"]", timeout=10)
                nav.definir_valor(
                    "xpath", "//div[@class=\"filter-modal-content\"]//input[@name=\"NR_SEQ_TERCEIRO\"]", str(seq_terceiro))
                nav.aguardar(0.5)
                nav.executar_javascript("document.activeElement.blur();")

                seq_encontrado = None
                for tentativa in range(1, 11):
                    nav.aguardar(0.5)
                    try:
                        seq_encontrado = nav.obter_texto(
                            "xpath", "//div[@class=\"filter-modal-content\"]//tasy-wtextboxlocator[@w-model=\"record['NR_SEQ_TERCEIRO']\"]//input[@ng-model=\"description\"]")
                    except Exception:
                        seq_encontrado = None
                    logger.info("[%s/10] - Nome [%s]",
                                tentativa, seq_encontrado)
                    if seq_encontrado:
                        break

                if not seq_encontrado:
                    status = "I"
                    status_msg = f"Não encontrou a sequência: {seq_terceiro}"
                    self.registrar_log("INFO", status_msg)
                    self.db.execute_non_query(
                        "Update hos_repasse_medico set status = :1, mensagem = :2 where nr_repasse = :3", (status, status_msg, nr_repasse))
                    continue

                nav.click_elemento(
                    "xpath", "//div[@class=\"filter-modal-content\"]//button[contains(.,'Filtrar')]")
                nav.aguardar(1)

                found = nav.aguardar_elemento_visivel(
                    "xpath", f"//div[@class=\"datagrid-grid-container\"]//div[@class=\"ui-widget-content slick-row even active\"]/div[contains(.,'{seq_terceiro}')]", timeout=10)
                if not found:
                    status = "I"
                    status_msg = f"Não encontrou a sequência: {seq_terceiro}"
                    self.registrar_log("INFO", status_msg)
                    self.db.execute_non_query(
                        "Update hos_repasse_medico set status = :1, mensagem = :2 where nr_repasse = :3", (status, status_msg, nr_repasse))
                    continue

                nav.click_elemento(
                    "xpath", f"//div[@class=\"datagrid-grid-container\"]//div[@class=\"ui-widget-content slick-row even active\"]/div[contains(.,'{seq_terceiro}')]")
                nav.aguardar_elemento_visivel(
                    "xpath", "//div[@class=\"wdbpanel-container\" and contains(.,'Repasse terceiros')]", timeout=20)

                nav.aguardar_elemento_visivel(
                    "xpath", f"//div[@class=\"datagrid-cell-content-wrapper \" and contains(.,'{nr_repasse}')]", timeout=2)
                nav.click_elemento(
                    "xpath", f"//div[@class=\"datagrid-cell-content-wrapper \" and contains(.,'{nr_repasse}')]")

                nav.click_elemento(
                    "xpath", "//span[contains(.,'Enviar E-mail')]")

                nav.aguardar_elemento_visivel(
                    "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Email destino')]", timeout=10)
                if self.config.dev_mode:
                    nav.definir_valor(
                        "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Email destino')]//input[@name=\"DS_EMAIL_DESTINO\"]", "aalves@austa.com.br")
                else:
                    nav.definir_valor(
                        "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Email destino')]//input[@name=\"DS_EMAIL_DESTINO\"]", email)

                nav.click_elemento(
                    "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Email destino')]//button[contains(.,'Enviar')]")

                aborted = nav.aguardar_elemento_visivel(
                    "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Operação abortada')]", timeout=5)
                if aborted:
                    _text = nav.obter_texto(
                        "xpath", "//div[@class=\"ngdialog-content\" and contains(.,'Operação abortada')]//div[@class=\"dialog-content\"]")
                    nav.click_elemento(
                        "xpath", "//div[@class=\"ngdialog-content\"]//button[contains(.,'OK')]")
                    status = "False"
                    status_msg = "Falha no envio do email"
                    self.registrar_log("INFO", status_msg)
                    self.db.execute_non_query(
                        "Update hos_repasse_medico set status = :1, mensagem = :2 where nr_repasse = :3", (status, status_msg, nr_repasse))
                else:
                    status = "E"
                    status_msg = "Enviado"
                    self.db.execute_non_query(
                        "Update hos_repasse_medico set status = :1, mensagem = :2 where nr_repasse = :3", (status, status_msg, nr_repasse))

            except Exception:
                logger.exception("Erro ao processar repasse %s", nr_repasse)
                self.registrar_log(
                    "ERROR", f"Erro ao processar repasse {nr_repasse}")

    def finalizar(self) -> None:
        self.registrar_log("INFO", "Fim Robô")
        if self.db:
            try:
                params = {"P_ID_EXECUCAO": self.controle_execucao or 0,
                          "P_STATUS": "Concluido", "P_OBSERVACOES": "-"}
                try:
                    self.db.call_procedure(
                        "ROBO_RPA.PR_FINALIZAR_EXECUCAO", params)
                except Exception:
                    logger.debug(
                        "PR_FINALIZAR_EXECUCAO não disponível em ambiente de teste")
            finally:
                if self._owns_db:
                    try:
                        self.db.close()
                    except Exception:
                        logger.exception("Erro ao fechar conexão com o banco")

        if self.navegador and self._owns_browser:
            try:
                if hasattr(self.navegador, "fechar_navegador"):
                    getattr(self.navegador, "fechar_navegador")()
            except Exception:
                logger.exception("Erro ao fechar navegador")
