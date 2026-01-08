
from __future__ import annotations

import oracledb
from logs.logger_config import logger
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable
from comandos import WebController, DBClient
from dotenv import load_dotenv

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
    id_unidade: str
    id_projeto: str
    caminho_chrome_driver: str

    @classmethod
    def from_env(cls) -> "Config":
        caminho = os.environ.get("CAMINHO_PADRAO", " ")
        dev = os.environ.get("DEV", "False").lower() in ("1", "true", "yes")
        user = os.environ.get("BD_USUARIO", "")
        pwd = os.environ.get("BD_SENHA", "")
        lista = os.environ.get("AUSTA_BD_ORACLE_DEV", "")
        host, port, service = ("", "", "")
        id_unidade = os.environ.get("ID_UNIDADE", "")
        id_projeto = os.environ.get("ID_PROJETO", "")
        driver = os.environ.get("CAMINHO_CHROME_DRIVER", "")

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
            id_unidade=id_unidade,
            id_projeto=id_projeto,
            caminho_chrome_driver=driver
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

        if self.navegador is None:  # Instancia o navegador
            try:
                self.navegador = WebController()
                self._owns_browser = True
            except Exception as e:
                logger.exception("Falha ao instanciar o navegador: {e}")
                raise

        if self.db is None:  # Conecta ao banco de dados
            try:
                self.db = DBClient(self.config)
                logger.info("Conectado ao Oracle em %s:%s/%s", self.config.db_host,
                            self.config.db_port, self.config.db_service)
                self._owns_db = True
            except Exception as e:
                logger.exception("Falha ao conectar no Oracle: {e}")
                raise

        try:
            if self.db:
                # Obtém parâmetros do banco
                self.url_tasy = self.proc_obter_parametro(
                    chave="URL_TASY", id_projeto=9999, id_unidade=None, dev=None)

                self.credencial_tasy = self.proc_obter_parametro(
                    chave="CREDENCIAL_TASY", id_projeto=9999, id_unidade=None, dev=None)

                self.usuario_tasy = self.credencial_tasy.split(";")[0]
                self.senha_tasy = self.credencial_tasy.split(";")[1]

                # Cria variável para receber o valor de saída
                cursor = self.db.cursor()
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

    def registrar_log(self, tipo_log: str, mensagem: str, tipo_registro: Optional[str] = None) -> None:
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
                          "p_registro_id": tipo_registro or "", "p_mensagem": mensagem}
                self.db.call_procedure("ROBO_RPA.PR_REGISTRAR_LOG", params)
            except Exception as e:
                logger.exception(f"Falha ao registrar log no banco: {e}")

    def proc_obter_parametro(self, chave: str, id_unidade: int, id_projeto: int, dev: str) -> Optional[str]:

        if not id_unidade:
            id_unidade = int(self.config.id_unidade)
        if not id_projeto:
            id_projeto = int(self.config.id_projeto)
        if not dev:
            dev = str(self.config.dev_mode)

        if not self.db:
            raise RuntimeError("Banco não conectado")

        try:
            cursor = self.db.cursor()
            out_valor = cursor.var(oracledb.DB_TYPE_VARCHAR)

            params = {
                "P_ID_UNIDADE": id_unidade,
                "P_ID_PROJETO": id_projeto,
                "P_CHAVE": chave,
                "P_DEV": dev,
                "P_VALOR": out_valor
            }

            self.db.call_procedure(
                "ROBO_RPA.RPA_PARAMETRO_OBTER", params)

            valor = out_valor.getvalue()
            return valor
        except Exception as e:
            logger.exception(f"Erro ao obter parâmetro {chave}: {e}")
            return None

    def login_tasy(self) -> bool:
        logger.info("Iniciando navegador Tasy")
        try:

            if not self.url_tasy:
                raise RuntimeError("URL do Tasy não configurada")

            self.navegador.navegar(self.url_tasy)
            self.navegador.aguardar_elemento_visivel(
                f"id", "loginUsername", timeout=60)
            self.navegador.definir_valor(
                f"id", "loginUsername", self.usuario_tasy, timeout=5)
            self.navegador.definir_valor(
                f"id", "loginPassword", self.senha_tasy, timeout=5)
            self.navegador.click_elemento(
                f"css", "#loginForm > input.btn-green.w-login-button.w-login-button--green", timeout=10)

            if not self.navegador.aguardar_elemento_visivel(
                    f"xpath", "//div[@class='ngdialog-content']//button", timeout=5):
                self.registrar_log("INFO", f"Login Tasy: False")
                return False

            self.registrar_log("INFO", f"Login Tasy: True")
            # Os cliques abaixo são para fechar pop-ups que podem aparecer após o login
            self.navegador.click_elemento(
                f"xpath", "//div[@class='ngdialog-content']//button", timeout=5)
            self.navegador.click_elemento(
                f"xpath", "//div[@class='ngdialog-content' and contains(.,'TasyNative')]//span[contains(.,'Fechar')]", timeout=5, js=True)
            self.navegador.click_elemento(
                f"css", "#ngdialog2 > div.ngdialog-content > div.dialog-box.dialog-default > div.dialog-footer.ng-scope > div:nth-child(3) > tasy-wdlgpanel-button > button > span", timeout=5)
            self.navegador.click_elemento(
                f"xpath", "//button[text()='Agora não']", timeout=5, js=True)
            self.navegador.click_elemento(
                f"xpath", "//div[contains(.,'Comunicação Interna')]/div/button", timeout=5, js=True)
            self.navegador.click_elemento(
                f"xpath", "//div[contains(.,'Administração do Sistema')]/div/button", timeout=5, js=True)

            self.tasy_navegar_menu_telas("Repasse para Terceiros")
            return True
        except Exception as e:
            logger.exception(f"Falha no login Tasy: {e}")
            self.registrar_log("ERROR", "Login Tasy: False")
            return False

    def tasy_navegar_menu_telas(self, tela: str) -> None:
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
        sql = (
            "SELECT cnpj, razao_social, seq_terceiro, nr_repasse, nr_titulo, dt_lib_titulo, email, dt_ult_envio_email, dt_lib_repasse,cd_estabelecimento "
            "FROM TASY.RPA_EMAIL_REPASSE_V "
            "WHERE DT_LIB_TITULO >= TO_DATE('01/09/2025', 'DD/MM/YYYY') and cd_estabelecimento = 4 "
            "ORDER BY DT_LIB_TITULO ASC "
            "FETCH FIRST 50 ROWS ONLY"
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
            cd_estabelecimento = row.get("cd_estabelecimento")

            sql_check = "SELECT 1 FROM hos_repasse_medico WHERE nr_repasse = :1"
            existe = self.db.execute_scalar(sql_check, (nr_repasse,))
            if existe:
                continue

            sql_insert = (
                "INSERT INTO hos_repasse_medico (cnpj, razao_social, seq_terceiro, nr_repasse, nr_titulo, dt_lib_titulo, email, dt_ult_envio_email, status, dt_lib_repasse, cd_estabelecimento) "
                "VALUES (:1, :2, :3, :4, :5, TO_DATE(:6, 'DD/MM/YYYY HH24:MI:SS'), :7, TO_DATE(:8, 'DD/MM/YYYY HH24:MI:SS'), 'P', TO_DATE(:9, 'DD/MM/YYYY HH24:MI:SS'), :10)"
            )
            params = (cnpj, razao_social, seq_terceiro, nr_repasse,
                      nr_titulo, dt_lib_titulo, email, dt_ult_envio_email, dt_lib_repasse, cd_estabelecimento)
            try:
                self.db.execute_non_query(sql_insert, params)
                qtd_importados += 1
                self.registrar_log(
                    "INFO", f"Inserido na tabela HOS_REPASSE_MEDICO: Terceiro: {seq_terceiro} - Repasse: {nr_repasse} - Título: {nr_titulo} - CNPJ: {cnpj} - Status: P - Estabelecimento: {cd_estabelecimento}", nr_repasse)
            except Exception as e:
                logger.exception("Falha ao inserir repasse %s", nr_repasse)

        self.registrar_log(
            "INFO", f"Dados Importados com Sucesso: [{qtd_importados}/{len(rows)}]")
        return qtd_importados

    def executar(self) -> None:
        self.registrar_log(
            "INFO", f"Inicio robô - Id Exec: {self.controle_execucao}")

        tabela = self.db.execute_query(
            "select * from hos_repasse_medico where status = 'P'")
        '''if not tabela:
            self.registrar_log("INFO", "Sem repasses para realizar o envio")
            return'''

        self.login_tasy()
        return

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
                    "xpath", '//div[@class="token-filter-container ng-scope"]/tasy-wlabel', timeout=10)
                nav.click_elemento(
                    "xpath", '//div[@class="token-filter-container ng-scope"]/tasy-wlabel')

                nav.aguardar_elemento_visivel(
                    "xpath", '//div[@class="filter-modal-content"]', timeout=10)
                nav.definir_valor(
                    "xpath", '//div[@class="filter-modal-content"]//input[@name="NR_SEQ_TERCEIRO"]', str(seq_terceiro))
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
                    "xpath", '//div[@class="filter-modal-content"]//button[contains(.,"Filtrar")]')
                nav.aguardar(1)

                found = nav.aguardar_elemento_visivel(
                    "xpath", f'//div[@class="datagrid-grid-container"]//div[@class="ui-widget-content slick-row even active"]/div[contains(.,{seq_terceiro})]', timeout=10)
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
                    "xpath", '//div[@class="ngdialog-content" and contains(.,"Email destino")]', timeout=10)

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
