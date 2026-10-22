Olá, professor(a) e colegas!

🔗 **Repositório:** https://github.com/SEU-USUARIO/genai-testes-integracao

**Cenário:** um checkout de e-commerce com 3 serviços REST. O **Pedidos** consulta preço e reserva no **Estoque**, cobra no **Pagamentos** (com `Idempotency-Key` e 1 retentativa) e, se a cobrança falhar, **libera a reserva** (compensação). Os 3 sobem em memória com FastAPI, e as chamadas entre eles passam por um transporte "espião" que deixa injetar timeout, 5xx e JSON corrompido. São 42 testes, todos passando.

Usei **três tipos de prompt**, com o Claude como LLM:

**1) Cenários de integração + dados de teste**
- *Influência:* foi o que deu mais **cobertura de regra de negócio**. Na v1 ("gere testes de integração para uma API de pedidos") saíram testes de endpoint isolado, com rotas inventadas e só caminho feliz. Quando coloquei o **contexto dos 3 serviços** e pedi o "efeito esperado em **cada** serviço", os casos mudaram de natureza: "estoque insuficiente → 409 **e nenhuma cobrança feita**", "cartão recusado → **estoque devolvido**". Também apareceram casos que eu não tinha pensado, como a ordem das chamadas e a chave de idempotência.
- *Ajustes:* (a) a v2 gerava `mock.patch` no cliente HTTP, o que é teste unitário disfarçado. Resolvi passando a **fixture existente** e um **exemplo de teste** no prompt (few-shot), e o código passou a rodar sem edição. (b) Pedi explicitamente **valores-limite**, e vieram limites "de integração" como *exatamente o estoque* e *estoque + 1*, que dependem do estado do outro serviço. (c) Troquei à mão um teste de concorrência com threads que era instável.

**2) Casos de erro / falhas de comunicação**
- *Influência:* foi o que mais **aumentou a diversidade**. Na v1 ("gere casos de erro"), a LLM entendeu "erro" como validação de entrada (4xx) e repetiu o prompt 1. Na v2 dei uma **taxonomia de falhas** (timeout, conexão recusada, 5xx, corpo não-JSON, JSON incompleto) e pedi para cruzar com cada chamada externa. Também pedi que ela **respondesse antes de codar**: *qual status? há efeito colateral a desfazer? há risco de cobrança duplicada?* Desse raciocínio saíram os melhores casos: timeout no pagamento → retentativa com a **mesma** chave → **uma** cobrança só; e "**a compensação também falha**", que me fez alterar o código de produção para marcar o pedido como `compensation_pending`.
- *Ajustes:* deixar as **regras de retry explícitas** no prompt (ela assumiu que haveria retry no estoque também) e podar combinações redundantes da matriz.

**3) Contrato de API (consumer-driven)**
- *Influência:* deu **menos casos, mas mais precisos**. Na v1, colando o código dos providers, ela gerou um contrato que validava todos os campos. Isso quebraria por mudanças irrelevantes. Na v2 pedi: "liste **o que o consumer lê ou envia**; teste só isso, direto no provider". Assim surgiram dependências implícitas: `price_cents` precisa ser **inteiro** e a **idempotência é um contrato de comportamento**, não só de formato.
- *Ajuste:* ela sugeriu Pact com broker. Mantive pytest puro pelo tamanho do exercício.

**Como medi a qualidade:** fiz um pequeno **teste de mutação** (tabela no README). Introduzi 7 bugs e vi qual suíte detectava cada um. **Nenhum tipo de prompt pegou tudo sozinho.** Remover a retentativa só foi pego pelos casos de erro. O total que ignora a quantidade só foi pego pelos cenários. O provider que deixa de exigir `Idempotency-Key` só foi pego pelo contrato. E quando o provider renomeou `price_cents`, 17 testes quebraram com mensagens genéricas, mas o de contrato apontou o campo exato.

**Boas práticas que levo:**
1. **Contexto concreto vence instrução genérica.** Endpoints, campos e regras no prompt eliminam a "alucinação de API".
2. **Peça os efeitos colaterais em cada serviço.** É isso que transforma um teste de API em teste de *integração*.
3. **Mostre a infraestrutura e um exemplo** (few-shot) para o código sair executável e no padrão do projeto.
4. **Dê uma taxonomia e peça o raciocínio antes do código.** A diversidade vira sistemática em vez de aleatória.
5. **Revise sempre.** A LLM foi um ótimo copiloto para *lembrar cenários*, mas errou regras que não estavam no prompt. Quem decide o comportamento correto continua sendo a gente.

Fico curioso(a): alguém testou prompts para **gerar dados de teste realistas** (ex.: massa de dados para contratos de API)? Como lidaram com consistência entre serviços?
