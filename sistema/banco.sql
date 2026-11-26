-- =====================================================================
-- GestEnergia — criacao do banco e dados de exemplo (issue #7)
--
-- Rodar:  mysql -u root -p < banco.sql
-- No Docker este script roda sozinho na primeira subida do container do
-- MySQL (docker-entrypoint-initdb.d). Para reaplicar:
--   docker compose down -v && docker compose up -d db
--
-- As duas primeiras instrucoes (CREATE DATABASE + USE) sao obrigatorias:
-- o Docker executa o script sem banco selecionado.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS gestenergia
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE gestenergia;

-- Ordem de remocao inversa a de criacao, por causa das chaves estrangeiras.
DROP TABLE IF EXISTS alertas;
DROP TABLE IF EXISTS leituras_energia;
DROP TABLE IF EXISTS medidores;
DROP TABLE IF EXISTS setores;
DROP TABLE IF EXISTS usuarios_sistema;

-- ---------------------------------------------------------------------
-- usuarios_sistema
-- Regra 7: OPERADOR registra e importa leituras; GESTOR faz tudo.
-- A senha vai SEMPRE em hash (werkzeug.security), nunca em texto.
-- ---------------------------------------------------------------------
CREATE TABLE usuarios_sistema (
  id          INT           NOT NULL AUTO_INCREMENT,
  nome        VARCHAR(120)  NOT NULL,
  email       VARCHAR(180)  NOT NULL,
  senha_hash  VARCHAR(255)  NOT NULL,
  perfil      ENUM('OPERADOR', 'GESTOR') NOT NULL,
  ativo       BOOLEAN       NOT NULL DEFAULT TRUE,
  criado_em   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuario_email (email)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- setores
-- Regra 9: arquivo_modelo aponta para o .pkl daquele setor.
-- Regra 10: limite_consumo_kwh e o percentil 99 do consumo do setor no
--           periodo de treino. Fica NULL ate a issue #44 calcular.
-- ---------------------------------------------------------------------
CREATE TABLE setores (
  id                  INT           NOT NULL AUTO_INCREMENT,
  nome                VARCHAR(120)  NOT NULL,
  descricao           VARCHAR(255)  NULL,
  limite_consumo_kwh  DECIMAL(10,3) NULL,
  arquivo_modelo      VARCHAR(120)  NULL,
  tem_fator_potencia  BOOLEAN       NOT NULL DEFAULT FALSE,
  ativo               BOOLEAN       NOT NULL DEFAULT TRUE,
  criado_em           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_setor_nome (nome),
  CONSTRAINT ck_setor_limite_positivo
    CHECK (limite_consumo_kwh IS NULL OR limite_consumo_kwh > 0)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- medidores
-- Um medidor pertence a exatamente um setor. O setor do medidor e o que
-- define qual modelo preve e qual limite vale para o alerta.
-- ---------------------------------------------------------------------
CREATE TABLE medidores (
  id         INT           NOT NULL AUTO_INCREMENT,
  id_setor   INT           NOT NULL,
  codigo     VARCHAR(60)   NOT NULL,
  descricao  VARCHAR(255)  NULL,
  ativo      BOOLEAN       NOT NULL DEFAULT TRUE,
  criado_em  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_medidor_codigo (codigo),
  KEY ix_medidor_setor (id_setor),
  CONSTRAINT fk_medidor_setor FOREIGN KEY (id_setor)
    REFERENCES setores (id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- leituras_energia
-- Regra 3: um medidor NAO pode ter duas leituras com a mesma data_hora.
--          Garantido pela chave unica abaixo e validado no servico.
-- Regra 1: fator_potencia aceita NULL. So o setor Producao tem o dado.
-- Regra 4: consumo_previsto_kwh fica NULL com menos de 4 leituras.
--
-- As colunas reativa_* e co2_t existem porque a base da siderurgica tem
-- esses dados, mas NUNCA entram como atributo do modelo: sao do mesmo
-- periodo do alvo e vazariam a resposta.
-- ---------------------------------------------------------------------
CREATE TABLE leituras_energia (
  id                      BIGINT        NOT NULL AUTO_INCREMENT,
  id_medidor              INT           NOT NULL,
  data_hora               DATETIME      NOT NULL,
  consumo_kwh             DECIMAL(10,3) NOT NULL,
  fator_potencia          DECIMAL(4,3)  NULL,
  consumo_previsto_kwh    DECIMAL(10,3) NULL,
  reativa_atrasada_kvarh  DECIMAL(10,3) NULL,
  reativa_adiantada_kvarh DECIMAL(10,3) NULL,
  co2_t                   DECIMAL(10,5) NULL,
  criado_em               DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_leitura_medidor_data_hora (id_medidor, data_hora),
  KEY ix_leitura_data_hora (data_hora),
  CONSTRAINT fk_leitura_medidor FOREIGN KEY (id_medidor)
    REFERENCES medidores (id) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT ck_leitura_consumo_nao_negativo
    CHECK (consumo_kwh >= 0),
  CONSTRAINT ck_leitura_previsto_nao_negativo
    CHECK (consumo_previsto_kwh IS NULL OR consumo_previsto_kwh >= 0),
  CONSTRAINT ck_leitura_fator_entre_0_e_1
    CHECK (fator_potencia IS NULL OR (fator_potencia >= 0 AND fator_potencia <= 1))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- alertas
-- Regra 2: CONSUMO_ACIMA_LIMITE quando o previsto passa do limite do setor.
-- Regra 1: FATOR_POTENCIA_BAIXO quando o fator fica abaixo de 0,92, e
--          somente quando a leitura TEM o dado.
-- valor_observado e limite_referencia ficam guardados para auditoria:
-- permitem reconstruir por que o alerta foi aberto.
-- ---------------------------------------------------------------------
CREATE TABLE alertas (
  id                   BIGINT        NOT NULL AUTO_INCREMENT,
  id_leitura           BIGINT        NOT NULL,
  tipo                 ENUM('CONSUMO_ACIMA_LIMITE', 'FATOR_POTENCIA_BAIXO') NOT NULL,
  valor_observado      DECIMAL(10,3) NOT NULL,
  limite_referencia    DECIMAL(10,3) NOT NULL,
  mensagem             VARCHAR(255)  NULL,
  status               ENUM('ABERTO', 'RESOLVIDO') NOT NULL DEFAULT 'ABERTO',
  criado_em            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolvido_em         DATETIME      NULL,
  id_usuario_resolucao INT           NULL,
  -- O que o gestor escreveu ao resolver (issue #28). Obrigatoria na resolucao,
  -- pelo CHECK abaixo: um alerta resolvido sem explicacao nao serve a auditoria,
  -- que e justamente para que resolvido_em e id_usuario_resolucao existem.
  observacao_resolucao VARCHAR(500)  NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_alerta_leitura_tipo (id_leitura, tipo),
  KEY ix_alerta_status (status),
  CONSTRAINT fk_alerta_leitura FOREIGN KEY (id_leitura)
    REFERENCES leituras_energia (id) ON DELETE CASCADE ON UPDATE CASCADE,
  -- RESTRICT nas duas acoes, e nao SET NULL/CASCADE, por imposicao do MySQL 8:
  -- uma coluna usada em CHECK nao aceita acao referencial (erro 3823). Como a
  -- coluna participa de ck_alerta_resolucao_coerente, a acao tem de ser RESTRICT.
  -- Efeito: usuario que ja resolveu alerta nao pode ser apagado, o que preserva
  -- a auditoria (alerta RESOLVIDO nunca perde quem o resolveu).
  CONSTRAINT fk_alerta_usuario FOREIGN KEY (id_usuario_resolucao)
    REFERENCES usuarios_sistema (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
  CONSTRAINT ck_alerta_resolucao_coerente
    CHECK (
      (status = 'ABERTO'    AND resolvido_em IS NULL     AND id_usuario_resolucao IS NULL
                            AND observacao_resolucao IS NULL)
      OR
      (status = 'RESOLVIDO' AND resolvido_em IS NOT NULL AND id_usuario_resolucao IS NOT NULL
                            AND observacao_resolucao IS NOT NULL)
    )
) ENGINE = InnoDB;

-- =====================================================================
-- Dados de exemplo
-- =====================================================================

-- Usuarios de demonstracao. Senhas:
--   gestor@gestenergia.local    -> gestor123
--   operador@gestenergia.local  -> operador123
-- Hashes no formato do werkzeug (pbkdf2:sha256). Para trocar uma senha:
--   python -c "from werkzeug.security import generate_password_hash as h; print(h('nova'))"
INSERT INTO usuarios_sistema (nome, email, senha_hash, perfil) VALUES
  ('Gestor de Energia', 'gestor@gestenergia.local',
   'pbkdf2:sha256:600000$Mt1a8U0HRkT8cbrH$8e9b46b2f22daeb05855e948482bcd8688439599a6a4962076970036b8c299b7',
   'GESTOR'),
  ('Operador de Planta', 'operador@gestenergia.local',
   'pbkdf2:sha256:600000$BtArYNOuqn7ix8aC$4de7a728a84e7994d6100fd0f759b5df6757aacc0130f78b811aed1674ef23b3',
   'OPERADOR');

-- Os 4 setores, com o limite_consumo_kwh medido pela issue #44: percentil 99
-- do consumo daquele setor NO PERIODO DE TREINO (os 10 primeiros meses), nunca
-- no ano todo nem no periodo de teste (regra 10). Em kWh por periodo de 15 min.
--
--   setor           serie             media   limite   acima do limite no ano
--   --------------- ----------------- ------- -------- -----------------------
--   Producao        siderurgica 2018    27,39  122,980   337 (0,96%) ~ 6,5/sem
--   Administrativo  MT_013, 2014        20,54   46,642   389 (1,11%) ~ 7,5/sem
--   Utilidades      MT_060, 2014         6,65   11,959   329 (0,94%) ~ 6,3/sem
--   Manutencao      MT_286, 2014        29,60   46,564   269 (0,77%) ~ 5,2/sem
--
-- Os numeros saem de data/processado/setores_kmeans.json, reexecutavel por
-- notebooks/setores_kmeans.py. Trocar o cliente de um setor obriga a recalcular
-- o limite aqui.
INSERT INTO setores (nome, descricao, limite_consumo_kwh, arquivo_modelo, tem_fator_potencia) VALUES
  ('Producao',       'Linha de producao. Base: Steel Industry Energy Consumption (UCI 851).',
   122.980, 'modelo_consumo_producao.pkl',       TRUE),
  ('Administrativo', 'Predio administrativo. Perfil de horario comercial. Cliente MT_013.',
    46.642, 'modelo_consumo_administrativo.pkl', FALSE),
  ('Utilidades',     'Compressores, bombas e refrigeracao. Perfil de 24 horas. Cliente MT_060.',
    11.959, 'modelo_consumo_utilidades.pkl',     FALSE),
  ('Manutencao',     'Oficina de manutencao. Cliente MT_286.',
    46.564, 'modelo_consumo_manutencao.pkl',     FALSE);

-- Um medidor por setor.
INSERT INTO medidores (id_setor, codigo, descricao)
SELECT id, CONCAT('MED-', UPPER(LEFT(nome, 4))), CONCAT('Medidor principal do setor ', nome)
FROM setores;

-- Nenhuma leitura de exemplo: as leituras entram pela tela de registro
-- (issue #18) ou pela importacao de CSV (issue #19), que e o caminho que
-- gera previsao e alertas de verdade.

-- Conferencia rapida do que foi criado.
SELECT 'usuarios' AS tabela, COUNT(*) AS total FROM usuarios_sistema
UNION ALL SELECT 'setores',   COUNT(*) FROM setores
UNION ALL SELECT 'medidores', COUNT(*) FROM medidores
UNION ALL SELECT 'leituras',  COUNT(*) FROM leituras_energia
UNION ALL SELECT 'alertas',   COUNT(*) FROM alertas;
