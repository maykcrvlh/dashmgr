# Segurança

O dashmgr controla um navegador já logado em sistemas internos e permite operar esses sistemas pelo painel web. Por isso, problemas de segurança são levados a sério.

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use a aba **Security → Report a vulnerability** deste repositório (aviso privado do GitHub). Se possível, inclua:

- a versão do dashmgr (aparece no rodapé do programa e do painel web);
- o passo a passo para reproduzir;
- o impacto que você identificou.

Vamos responder assim que possível e combinar com você a divulgação depois da correção.

## Escopo

Entram no escopo:

- **Painel web:** autenticação, sessões, CSRF, injeção e acesso remoto às telas.
- **Instalador:** permissões da pasta, regra de firewall e registro no Windows.
- **Dados sensíveis:** o armazenamento da senha (hash) e dos cookies de sessão (DPAPI).

## Recomendações de uso

- Use em rede interna ou por VPN. Não exponha a porta do painel web na internet.
- Ative o HTTPS (`cert.pem` e `key.pem`) e use uma senha forte.
- Revise periodicamente as **Sessões** abertas no painel web.
