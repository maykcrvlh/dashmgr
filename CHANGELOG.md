# Changelog

Todas as mudanças relevantes do **dashmgr** ficam registradas aqui.
O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [v1] — 2026-10-08

Primeira versão pública, com o nome **dashmgr**.

### Telas
- Um link por monitor, em tela cheia, aberto com um clique ou automaticamente no logon do Windows.
- Mapa das telas com arrastar e soltar. Cada link tem uma *posição* fixa, e soltar sobre um monitor ocupado troca os dois links de lugar.
- Monitores identificados pelo ID de hardware, com a posição na área de trabalho como alternativa. O vínculo continua certo quando o Windows renumera as telas.
- Mudanças aplicadas na hora: posição, URL, ativar/desativar, tela cheia e login separado mexem só nas telas afetadas.
- Auto refresh por link, com intervalo em segundos (mínimo de 5).
- Botões **Abrir**, **Fechar**, **Recarregar telas** e **Identificar**, e o atalho global **Ctrl+Alt+Q** para fechar a tela sob o mouse.

### Login
- Login compartilhado: todas as telas são janelas de um único Chrome, controlado localmente pelo Chrome DevTools Protocol.
- Opção **Login separado** por link, para usar outra conta no mesmo sistema.
- Cookies de sessão guardados a cada minuto e ao fechar (criptografados com a DPAPI) e restaurados quando o Chrome abre de novo.

### Painel web
- Acesso pelo navegador e pelo celular, na porta 888 (configurável), com senha guardada como hash PBKDF2-SHA256.
- **Acessar**: imagem ao vivo de uma tela específica, com mouse, teclado e colar texto, sem RDP.
- **Sessões**: lista quem está conectado e permite derrubar uma sessão ou todas as outras.
- Bloqueio por tentativas, proteção contra CSRF, cabeçalhos de segurança e aviso de edição simultânea.
- HTTPS opcional, com `cert.pem` e `key.pem` na pasta do programa.

### Instalação
- Instalador visual próprio (`dashmgr_instalador_v1.exe`), em 5 etapas.
- Detecta e migra instalações anteriores (Telas NOC e Painel Multi-Telas), mantendo links, posições e senha.
- Regra de firewall restrita às redes Privada e Domínio, com aviso quando a rede está marcada como Pública.
- Início automático com o Windows, atalho na área de trabalho e registro em *Aplicativos instalados*.
- Ao gerar o pacote, detecta quando o antivírus remove o executável (falso positivo do PyInstaller).

### Segurança
- O código publicado não tem senha padrão. O painel web só aceita login depois que a senha é definida.

## Antes da v1

Versões internas, não publicadas, com os nomes **Painel Multi-Telas** e **Telas NOC**.
