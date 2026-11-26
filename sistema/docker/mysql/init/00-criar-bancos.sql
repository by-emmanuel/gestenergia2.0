-- Roda antes do banco.sql, na primeira vez que o container do MySQL sobe.
-- Cria o banco de producao e o banco usado pelos testes de integracao,
-- e da permissao ao usuario da aplicacao nos dois.

CREATE DATABASE IF NOT EXISTS gestenergia
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS gestenergia_test
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

GRANT ALL PRIVILEGES ON gestenergia.*      TO 'gestenergia'@'%';
GRANT ALL PRIVILEGES ON gestenergia_test.* TO 'gestenergia'@'%';
FLUSH PRIVILEGES;
