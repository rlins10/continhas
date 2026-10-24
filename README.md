# Continhas

Gera folhas de atividades em PDF com contas sorteadas aleatoriamente, a partir
de templates em PDF. Os templates e a posição dos quadros são descritos em um
único arquivo YAML.

Operações disponíveis:

- Adição
- Subtração (o resultado nunca é negativo)
- Multiplicação
- Divisão (sempre exata, com a chave em "L" no padrão brasileiro)

## Instalação

A instalação é feita pelo `pyproject.toml`. Na pasta do projeto:

```sh
pip install .
```

Para um programa de linha de comando, o `pipx` costuma ser a melhor opção, pois
cria um ambiente isolado:

```sh
pipx install .
```

Em distribuições Linux que bloqueiam o `pip` global, use um ambiente virtual:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Para desenvolver (alterações no `continhas.py` valem sem reinstalar):

```sh
pip install -e .
```

Depois da instalação, o comando `continhas` fica disponível.

### Dependências

Instaladas automaticamente a partir do `pyproject.toml`:

| Dependência | Para quê |
|-------------|----------|
| Python 3.8 ou mais novo | executar o programa |
| [PyMuPDF](https://pymupdf.readthedocs.io/) (`pymupdf`) | ler o template e desenhar as contas no PDF |
| [questionary](https://github.com/tmbo/questionary) | menus e perguntas no terminal |
| [PyYAML](https://pyyaml.org/) (`pyyaml`) | ler o arquivo de configuração |

## Uso

```sh
continhas
```

Opções:

- `-c ARQUIVO`, `--config ARQUIVO`: usa outro arquivo de configuração em vez
  do padrão.

Fluxo:

1. Escolha a operação (ou **Sair** para encerrar o programa).
2. Informe a quantidade de dígitos (de 1 a 6) de cada número.
3. Escolha o template. O template padrão já vem marcado. Se houver só um
   template configurado, esta pergunta é pulada.
4. O PDF é salvo na pasta atual como `operacao-AAAAMMDD_HHMM.pdf`
   (por exemplo, `divisao-20261024_1403.pdf`). Se o arquivo já existir, é
   acrescentado `_2`, `_3` e assim por diante.
5. O menu volta a aparecer. O programa só termina quando você escolhe **Sair**.

Regras de dígitos:

- **Subtração:** o subtraendo não pode ter mais dígitos que o minuendo.
- **Divisão:** o divisor não pode ter mais dígitos que o dividendo, e é sempre
  maior ou igual a 2.

## Configuração

O arquivo fica em `~/.config/continhas/config.yaml` (ou em
`$XDG_CONFIG_HOME/continhas/config.yaml`, se essa variável estiver
definida).

Na primeira execução, se o arquivo não existir, o programa cria a pasta com um
`config.yaml` de exemplo e a subpasta `templates/`, e orienta onde copiar o PDF
do template. Depois é só editar o arquivo.

### Exemplo

```yaml
# Template que já vem marcado na lista de seleção.
padrao:
  template: criancas

templates:
  criancas:
    nome: Crianças sentadas
    caminho: templates/criancas.pdf
    titulo: [50, 30, 160, 42]
    grade:
      colunas: 4
      linhas: 4
      x: 33.5
      y: 50.0
      passo_x: 40.5
      passo_y: 46.5
      largura: 22.5

  irregular:
    nome: Seis quadros
    caminho: ~/atividades/seis.pdf
    quadros:
      - {x: 30.0, y: 60.0, largura: 40.0}
      - {x: 100.0, y: 60.0, largura: 40.0}
```

### Campos

Todas as medidas são em **milímetros**, contadas a partir do canto superior
esquerdo da página.

| Campo | Descrição |
|-------|-----------|
| `padrao.template` | chave do template que vem marcado na seleção (se omitido, o primeiro da lista) |
| `templates.<chave>.nome` | nome mostrado na lista de seleção (se omitido, usa a chave) |
| `templates.<chave>.caminho` | PDF do template; relativo à pasta do `config.yaml`, ou absoluto, ou com `~` |
| `templates.<chave>.titulo` | retângulo do título: `[x esquerda, y topo, x direita, y base]` (opcional) |
| `templates.<chave>.grade` | grade regular de quadros (veja abaixo) |
| `templates.<chave>.quadros` | lista de quadros um a um, para layouts irregulares |

Defina `grade`, `quadros` ou os dois (os quadros da lista são somados aos da
grade).

**`grade`:** `colunas`, `linhas`, `x`, `y`, `passo_x`, `passo_y` e, opcionalmente,
`largura`.

**`quadros`:** cada item tem `x`, `y` e, opcionalmente, `largura`.

Nos dois casos:

- `x` e `y` são a origem da conta: o canto esquerdo e a linha de base do
  primeiro número (na grade, valem para o primeiro quadro).
- `passo_x` e `passo_y` são as distâncias entre um quadro e o seguinte.
- `largura` é a distância da origem até a borda direita da conta. Contas
  armadas (adição, subtração e multiplicação) são alinhadas à direita nessa
  borda. O valor padrão é `22.5`.

## Licença

GNU General Public License, versão 2 ou posterior.
