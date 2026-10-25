#!/usr/bin/env python3
#
# continhas.py
#
# Copyright 2026 Renato Lins <renato@devel03>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import argparse
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import pymupdf
import questionary
import yaml


FONTE = "cour"
TAMANHO_FONTE = 16
COR = (0, 0, 0)
ESPESSURA_LINHA = 1.0

# Limite de dígitos para que a conta caiba no quadro.
MIN_DIGITOS = 1
MAX_DIGITOS = 6

# Valores usados quando o YAML não informa o título ou a largura da conta.
TITULO_PADRAO = (50.0, 30.0, 160.0, 42.0)
TITULO_FONTE_PADRAO = "cour"
TITULO_TAMANHO_PADRAO = 20.0
LARGURA_CONTA_PADRAO = 22.5

# Fontes que o PyMuPDF já traz embutidas (não precisam de arquivo).
FONTES_EMBUTIDAS = frozenset([
    "helv", "heit", "hebo", "hebi",   # Helvetica: normal, itálico, negrito, negrito itálico
    "tiro", "tiit", "tibo", "tibi",   # Times
    "cour", "coit", "cobo", "cobi",   # Courier
])

# Os templates seguem a convenção templates/template_<chave>.pdf.
PASTA_TEMPLATES = "templates"
CHAVE_VALIDA = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def nome_pdf_template(chave):
    """Nome do PDF de um template, para poder listar com template_*.pdf."""
    return f"template_{chave}.pdf"

NOME_APP = "continhas"
PREFIXO_ARQUIVO = "continhas"  # continhas_<operacao>-<data>.pdf
FONTE_RESERVA = "helv"         # usada quando a fonte pedida não está disponível
SAIR = "Sair"

CONFIG_INICIAL = """\
# Configuração do continhas.
#
# Todas as medidas são em milímetros, contadas a partir do canto superior
# esquerdo da página. Caminhos relativos são relativos a esta pasta; também
# são aceitos caminhos absolutos e "~".
#
# Convenção: a chave do template é minúscula, sem acento nem espaço, e o PDF
# se chama templates/template_<chave>.pdf (assim dá para listar com
# template_*.pdf).

# Configurações gerais.
geral:
  # Pasta onde os PDFs gerados são salvos (criada se não existir). Caminho
  # relativo vale a partir da pasta onde o programa é executado.
  pasta_destino: ~/continhas

# Template que já vem marcado na lista de seleção.
padrao:
  template: default

# Fontes extras (opcional): dê um apelido e aponte para um arquivo .ttf ou .otf.
# fontes:
#   comic: ~/.local/share/fonts/ComicSansMS.ttf
#   comic-neue: ~/.local/share/fonts/ComicNeue-Regular.otf

templates:
  default:
    nome: Template padrão
    # Se omitido, o caminho é templates/template_<chave>.pdf
    caminho: templates/template_default.pdf
    titulo:
      # Retângulo do título: [x esquerda, y topo, x direita, y base].
      retangulo: [50, 30, 160, 42]
      # Apelido definido em "fontes" ou fonte embutida (helv, tiro, cour e as
      # variantes em itálico/negrito).
      fonte: cour
      tamanho: 20
      maiusculas: true
    # Grade regular de quadros. x e y são a origem da conta no primeiro quadro
    # (canto esquerdo e linha de base do primeiro número); passo_x e passo_y
    # são as distâncias entre quadros. largura é a distância da origem até a
    # borda direita da conta (usada para alinhar a conta à direita).
    grade:
      colunas: 4
      linhas: 4
      x: 33.5
      y: 50.0
      passo_x: 40.5
      passo_y: 46.5
      largura: 22.5
    # Para layouts irregulares, liste os quadros um a um (pode ser combinado
    # com a grade):
    # quadros:
    #   - {x: 30.0, y: 55.0, largura: 22.5}
    #   - {x: 80.0, y: 55.0, largura: 22.5}
"""


# --------------------------------------------------------------------------
# Configuração (YAML)
# --------------------------------------------------------------------------

class ConfigErro(Exception):
    """Erro de conteúdo no arquivo de configuração."""


class Quadro(NamedTuple):
    x: float        # origem da conta (mm)
    y: float        # linha de base do primeiro número (mm)
    largura: float  # origem -> borda direita da conta (mm)


class Fonte(NamedTuple):
    nome: str                # nome usado no PDF (embutida) ou apelido da fonte
    arquivo: Optional[Path]  # None para fontes embutidas


class Titulo(NamedTuple):
    retangulo: Tuple[float, float, float, float]
    fonte: Fonte
    tamanho: float
    maiusculas: bool


class Layout(NamedTuple):
    titulo: Titulo
    quadros: List[Quadro]


class Template(NamedTuple):
    chave: str
    nome: str
    caminho: Path
    layout: Layout


class Config(NamedTuple):
    padrao: str
    templates: Dict[str, Template]
    pasta_destino: Path
    avisos: List[str]  # problemas tolerados ao ler o arquivo (ex.: fonte inválida)


def caminho_config_padrao():
    """~/.config/continhas/config.yaml (respeita XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    base = Path(base) if base else Path.home() / ".config"
    return base / NOME_APP / "config.yaml"


def criar_config_inicial(caminho):
    """Cria a pasta de configuração com um config.yaml de exemplo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    (caminho.parent / "templates").mkdir(exist_ok=True)
    caminho.write_text(CONFIG_INICIAL, encoding="utf-8")


def _numero(valor, onde):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ConfigErro(f"{onde}: esperado um número, recebido {valor!r}.")
    return float(valor)


def _inteiro_positivo(valor, onde):
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise ConfigErro(f"{onde}: esperado um inteiro maior que zero, recebido {valor!r}.")
    return valor


def _obrigatorio(dados, chave, onde):
    if chave not in dados:
        raise ConfigErro(f"{onde}: falta o campo '{chave}'.")
    return dados[chave]


def _caminho_config(valor, pasta):
    """Expande '~' e resolve caminhos relativos a partir da pasta do YAML."""
    caminho = Path(str(valor)).expanduser()
    return caminho if caminho.is_absolute() else pasta / caminho


def _problema_fonte(arquivo):
    """Devolve None se o arquivo de fonte carrega; senão, o motivo do problema."""
    if not arquivo.is_file():
        return "arquivo não encontrado"
    try:
        pymupdf.Font(fontfile=str(arquivo))
    except Exception as erro:  # arquivo corrompido, formato não suportado etc.
        return f"arquivo de fonte inválido ({erro})"
    return None


def _ler_fontes(dados, pasta, avisos):
    """Lê a seção 'fontes'. Fontes com problema são ignoradas, com aviso."""
    bruto = dados.get("fontes")
    if bruto is None:
        return {}
    if not isinstance(bruto, dict):
        avisos.append("fontes: esperado um bloco 'apelido: caminho do arquivo'; seção ignorada.")
        return {}

    fontes = {}
    for apelido, caminho_fonte in bruto.items():
        onde = f"fontes.{apelido}"
        if not isinstance(caminho_fonte, str) or not caminho_fonte.strip():
            avisos.append(f"{onde}: esperado o caminho de um arquivo .ttf ou .otf; fonte ignorada.")
            continue
        arquivo = _caminho_config(caminho_fonte, pasta)
        motivo = _problema_fonte(arquivo)
        if motivo:
            avisos.append(f"{onde}: {motivo}: {arquivo}. Fonte ignorada.")
            continue
        fontes[str(apelido)] = arquivo
    return fontes


def _resolver_fonte(valor, fontes, onde, avisos):
    """Fonte desconhecida ou indisponível não impede o uso: cai na reserva."""
    nome = str(valor)
    if nome in fontes:
        return Fonte("fonte_" + re.sub(r"\W", "_", nome), fontes[nome])
    if nome.lower() in FONTES_EMBUTIDAS:
        return Fonte(nome.lower(), None)
    avisos.append(
        f"{onde}: fonte '{nome}' indisponível; usando {FONTE_RESERVA} (Helvetica). "
        f"Defina-a em 'fontes' ou use uma embutida ({', '.join(sorted(FONTES_EMBUTIDAS))})."
    )
    return Fonte(FONTE_RESERVA, None)


def _ler_titulo(dados, fontes, onde, avisos):
    bruto = dados.get("titulo")
    if bruto is None:
        bruto = {}
    if isinstance(bruto, (list, tuple)):  # forma curta: só o retângulo
        bruto = {"retangulo": bruto}
    onde_t = f"{onde}.titulo"
    if not isinstance(bruto, dict):
        raise ConfigErro(f"{onde_t}: esperado um bloco com retangulo, fonte e tamanho.")

    retangulo = bruto.get("retangulo", TITULO_PADRAO)
    if not isinstance(retangulo, (list, tuple)) or len(retangulo) != 4:
        raise ConfigErro(f"{onde_t}.retangulo: esperado [x0, y0, x1, y1].")
    retangulo = tuple(_numero(v, f"{onde_t}.retangulo") for v in retangulo)

    fonte = _resolver_fonte(bruto.get("fonte", TITULO_FONTE_PADRAO), fontes, f"{onde_t}.fonte", avisos)

    tamanho = bruto.get("tamanho", TITULO_TAMANHO_PADRAO)
    if isinstance(tamanho, bool) or not isinstance(tamanho, (int, float)) or tamanho <= 0:
        avisos.append(
            f"{onde_t}.tamanho: esperado um número maior que zero, recebido {tamanho!r}; "
            f"usando {TITULO_TAMANHO_PADRAO:g}."
        )
        tamanho = TITULO_TAMANHO_PADRAO

    maiusculas = bruto.get("maiusculas", True)
    if not isinstance(maiusculas, bool):
        avisos.append(f"{onde_t}.maiusculas: esperado true ou false, recebido {maiusculas!r}; usando true.")
        maiusculas = True

    return Titulo(retangulo, fonte, float(tamanho), maiusculas)


def _ler_quadros(dados, onde):
    quadros = []

    grade = dados.get("grade")
    if grade is not None:
        onde_g = f"{onde}.grade"
        if not isinstance(grade, dict):
            raise ConfigErro(f"{onde_g}: esperado um bloco com colunas, linhas, x, y, passo_x e passo_y.")
        colunas = _inteiro_positivo(_obrigatorio(grade, "colunas", onde_g), f"{onde_g}.colunas")
        linhas = _inteiro_positivo(_obrigatorio(grade, "linhas", onde_g), f"{onde_g}.linhas")
        x0 = _numero(_obrigatorio(grade, "x", onde_g), f"{onde_g}.x")
        y0 = _numero(_obrigatorio(grade, "y", onde_g), f"{onde_g}.y")
        passo_x = _numero(_obrigatorio(grade, "passo_x", onde_g), f"{onde_g}.passo_x")
        passo_y = _numero(_obrigatorio(grade, "passo_y", onde_g), f"{onde_g}.passo_y")
        largura = _numero(grade.get("largura", LARGURA_CONTA_PADRAO), f"{onde_g}.largura")
        for linha in range(linhas):
            for coluna in range(colunas):
                quadros.append(Quadro(x0 + coluna * passo_x, y0 + linha * passo_y, largura))

    lista = dados.get("quadros")
    if lista is not None:
        if not isinstance(lista, list):
            raise ConfigErro(f"{onde}.quadros: esperada uma lista.")
        for i, item in enumerate(lista, start=1):
            onde_q = f"{onde}.quadros[{i}]"
            if not isinstance(item, dict):
                raise ConfigErro(f"{onde_q}: esperado {{x, y, largura}}.")
            quadros.append(Quadro(
                _numero(_obrigatorio(item, "x", onde_q), f"{onde_q}.x"),
                _numero(_obrigatorio(item, "y", onde_q), f"{onde_q}.y"),
                _numero(item.get("largura", LARGURA_CONTA_PADRAO), f"{onde_q}.largura"),
            ))

    if not quadros:
        raise ConfigErro(f"{onde}: defina 'grade' e/ou 'quadros'.")
    return quadros


def _ler_pasta_destino(dados, avisos):
    """Pasta onde os PDFs são salvos (seção 'geral'); padrão: pasta atual."""
    geral = dados.get("geral")
    if geral is None:
        return Path(".")
    if not isinstance(geral, dict):
        avisos.append("geral: esperado um bloco com 'pasta_destino'; seção ignorada.")
        return Path(".")
    bruto = geral.get("pasta_destino")
    if bruto is None:
        return Path(".")
    if not isinstance(bruto, str) or not bruto.strip():
        avisos.append("geral.pasta_destino: esperado um caminho; usando a pasta atual.")
        return Path(".")
    return Path(bruto).expanduser()


def carregar_config(caminho):
    """Lê o YAML e devolve a configuração validada."""
    with open(caminho, encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)

    if not isinstance(dados, dict) or not isinstance(dados.get("templates"), dict) or not dados["templates"]:
        raise ConfigErro("o arquivo precisa ter a seção 'templates' com pelo menos um template.")

    pasta = caminho.parent
    avisos = []
    fontes = _ler_fontes(dados, pasta, avisos)
    templates = {}
    for chave, bruto in dados["templates"].items():
        chave = str(chave)
        onde = f"templates.{chave}"
        if not CHAVE_VALIDA.match(chave):
            raise ConfigErro(
                f"{onde}: chave inválida. Use letras minúsculas sem acento, números, "
                f"'-' ou '_' (ex.: default, atividade9)."
            )
        if not isinstance(bruto, dict):
            raise ConfigErro(f"{onde}: esperado um bloco com nome, caminho e quadros.")
        # Sem 'caminho', vale a convenção templates/template_<chave>.pdf.
        pdf = _caminho_config(
            bruto.get("caminho", Path(PASTA_TEMPLATES) / nome_pdf_template(chave)), pasta
        )
        templates[chave] = Template(
            chave=chave,
            nome=str(bruto.get("nome", chave)),
            caminho=pdf,
            layout=Layout(_ler_titulo(bruto, fontes, onde, avisos), _ler_quadros(bruto, onde)),
        )

    padrao = dados.get("padrao")
    if isinstance(padrao, dict):
        padrao = padrao.get("template")
    if padrao is None:
        padrao = next(iter(templates))
    padrao = str(padrao)
    if padrao not in templates:
        raise ConfigErro(
            f"padrao.template: '{padrao}' não existe em 'templates' "
            f"(disponíveis: {', '.join(templates)})."
        )

    return Config(padrao, templates, _ler_pasta_destino(dados, avisos), avisos)


# --------------------------------------------------------------------------
# Desenho no PDF
# --------------------------------------------------------------------------

def mm(x, y):
    """Converte milímetros para pontos do PyMuPDF."""
    fator = 72 / 25.4
    return pymupdf.Point(x * fator, y * fator)


def rect_mm(x0, y0, x1, y1):
    """Retorna um pymupdf.Rect baseado em milímetros."""
    fator = 72 / 25.4
    return pymupdf.Rect(x0 * fator, y0 * fator, x1 * fator, y1 * fator)


def largura_texto_mm(texto, fontsize=TAMANHO_FONTE, fontname=FONTE):
    """Calcula a largura do texto na fonte usada para impressão."""
    largura_pt = pymupdf.get_text_length(str(texto), fontname=fontname, fontsize=fontsize)
    return largura_pt * 25.4 / 72


def escrever(pagina, texto, x, y, fontsize=TAMANHO_FONTE):
    """Escreve texto usando coordenadas em milímetros."""
    pagina.insert_text(mm(x, y), str(texto), fontname=FONTE, fontsize=fontsize, color=COR)


def desenhar_linha(pagina, x1, y1, x2, y2, largura=ESPESSURA_LINHA):
    """Desenha uma linha gráfica real no PDF."""
    shape = pagina.new_shape()
    shape.draw_line(mm(x1, y1), mm(x2, y2))
    shape.finish(color=COR, width=largura)
    shape.commit()


def faixa_digitos(digitos):
    """Menor e maior número com a quantidade de dígitos informada."""
    return 10 ** (digitos - 1), (10 ** digitos) - 1


class Divisao:
    """Gera divisões exatas (resto zero) com quociente inteiro."""

    nome = "Divisão"
    slug = "divisao"

    def __init__(self, digitos_dividendo=3, digitos_divisor=1):
        if digitos_divisor > digitos_dividendo:
            raise ValueError(
                "O divisor não pode ter mais dígitos que o dividendo."
            )
        self.digitos_dividendo = digitos_dividendo
        self.digitos_divisor = digitos_divisor

    def gerar_valores(self):
        min_dividendo, max_dividendo = faixa_digitos(self.digitos_dividendo)
        min_divisor, max_divisor = faixa_digitos(self.digitos_divisor)

        # Divisor 1 é trivial; o mínimo passa a ser 2.
        self.divisor = random.randint(max(2, min_divisor), max_divisor)

        # Sorteia o QUOCIENTE e calcula o dividendo (quociente * divisor).
        # Assim a divisão é sempre exata, sem precisar de loop de tentativas.
        q_min = -(-min_dividendo // self.divisor)  # teto da divisão
        q_max = max_dividendo // self.divisor
        self.quociente = random.randint(q_min, q_max)
        self.dividendo = self.quociente * self.divisor

    def desenhar(self, pagina, x_inicio, y_inicio, largura_quadro=None):
        texto = str(self.dividendo)
        largura_dividendo = largura_texto_mm(texto)
        largura_divisor = largura_texto_mm(str(self.divisor))
        largura_quociente = largura_texto_mm(str(self.quociente))

        x_chave = x_inicio + largura_dividendo + 1.5
        x_divisor = x_chave + 2.0
        y_topo = y_inicio - 5.0
        y_linha = y_inicio + 2.0   # linha horizontal ABAIXO do divisor
        y_base = y_inicio + 12.0   # a barra vertical desce junto à área do quociente
        largura_l = max(10.0, largura_divisor + 4.0, largura_quociente + 4.0)

        escrever(pagina, texto, x_inicio, y_inicio)
        escrever(pagina, str(self.divisor), x_divisor, y_inicio)

        # Chave em formato de "L" invertido: vertical + horizontal sob o divisor.
        desenhar_linha(pagina, x_chave, y_topo, x_chave, y_base)
        desenhar_linha(pagina, x_chave, y_linha, x_chave + largura_l, y_linha)


class OperacaoVertical:
    """Base para contas armadas na vertical (x, +, -)."""

    nome = ""
    slug = ""
    sinal = ""

    def __init__(self, digitos_a=3, digitos_b=1):
        self.digitos_a = digitos_a
        self.digitos_b = digitos_b

    def gerar_valores(self):
        min_a, max_a = faixa_digitos(self.digitos_a)
        min_b, max_b = faixa_digitos(self.digitos_b)
        self.a = random.randint(min_a, max_a)
        self.b = random.randint(min_b, max_b)

    def desenhar(self, pagina, x_inicio, y_inicio, largura_quadro=LARGURA_CONTA_PADRAO):
        a = str(self.a)
        b = str(self.b)
        largura_a = largura_texto_mm(a)
        largura_b = largura_texto_mm(b)
        largura_sinal = largura_texto_mm(self.sinal)
        largura_conta = max(largura_a, largura_b + largura_sinal + 2.0)

        # A conta inteira fica encostada na direita do quadro; as unidades
        # dos dois números terminam na mesma coluna (x_direita).
        x_direita = x_inicio + largura_quadro
        x_esquerda = x_direita - largura_conta

        # Primeiro número alinhado à direita.
        escrever(pagina, a, x_direita - largura_a, y_inicio)

        # Sinal da operação e segundo número na linha seguinte.
        x_sinal = x_direita - largura_b - largura_sinal - 1.0
        escrever(pagina, self.sinal, x_sinal, y_inicio + 7.0)
        escrever(pagina, b, x_direita - largura_b, y_inicio + 7.0)

        # Linha horizontal real, logo abaixo do segundo número.
        desenhar_linha(
            pagina,
            x_esquerda,
            y_inicio + 9.5,
            x_direita + 1.0,
            y_inicio + 9.5,
        )


class Multiplicacao(OperacaoVertical):
    """Multiplicações com fatores inteiros positivos."""

    nome = "Multiplicação"
    slug = "multiplicacao"
    sinal = "x"


class Adicao(OperacaoVertical):
    """Adições com duas parcelas inteiras positivas."""

    nome = "Adição"
    slug = "adicao"
    sinal = "+"


class Subtracao(OperacaoVertical):
    """Subtrações cujo resultado nunca é negativo."""

    nome = "Subtração"
    slug = "subtracao"
    sinal = "-"

    def __init__(self, digitos_minuendo=3, digitos_subtraendo=2):
        if digitos_subtraendo > digitos_minuendo:
            raise ValueError(
                "O subtraendo não pode ter mais dígitos que o minuendo."
            )
        super().__init__(digitos_minuendo, digitos_subtraendo)

    def gerar_valores(self):
        super().gerar_valores()
        # Garante minuendo >= subtraendo (resultado nunca negativo).
        # Só pode ser necessário trocar quando os dois têm o mesmo número de dígitos.
        if self.b > self.a:
            self.a, self.b = self.b, self.a


class GeradorFolhaMatematica:
    def __init__(self, template):
        self.layout = template.layout
        self.doc = pymupdf.open(str(template.caminho))
        self.pagina = self.doc[0]

    def configurar_cabecalho(self, titulo_operacao):
        titulo = self.layout.titulo
        texto = titulo_operacao.upper() if titulo.maiusculas else titulo_operacao
        retangulo = rect_mm(*titulo.retangulo)

        # Se a fonte escolhida falhar na hora de escrever, tenta a reserva.
        for fonte in (titulo.fonte, Fonte(FONTE_RESERVA, None)):
            opcoes = {"fontname": fonte.nome}
            if fonte.arquivo is not None:
                opcoes["fontfile"] = str(fonte.arquivo)
            try:
                sobra = self.pagina.insert_textbox(
                    retangulo,
                    texto,
                    fontsize=titulo.tamanho,
                    align=pymupdf.TEXT_ALIGN_CENTER,
                    color=COR,
                    **opcoes,
                )
            except Exception as erro:
                if fonte.arquivo is None:
                    raise  # nem a fonte embutida funcionou: erro de verdade
                print(
                    f"Aviso: não consegui usar a fonte {fonte.arquivo.name} ({erro}); "
                    "usando Helvetica no título."
                )
                continue
            if sobra < 0:
                print(
                    "Aviso: o título não coube no retângulo e não foi escrito. "
                    "Aumente o retângulo ou diminua o tamanho da fonte."
                )
            return

    def preencher_grade(self, operacao_obj):
        for quadro in self.layout.quadros:
            operacao_obj.gerar_valores()
            operacao_obj.desenhar(self.pagina, quadro.x, quadro.y, quadro.largura)

    def salvar(self, nome_saida):
        self.doc.save(nome_saida)
        self.doc.close()


# --------------------------------------------------------------------------
# Interface de terminal
# --------------------------------------------------------------------------

def validar_digitos(valor):
    """Validador do questionary para a quantidade de dígitos."""
    if not valor.isdigit():
        return "Digite apenas números inteiros."
    if not MIN_DIGITOS <= int(valor) <= MAX_DIGITOS:
        return f"Digite um valor entre {MIN_DIGITOS} e {MAX_DIGITOS}."
    return True


def perguntar_digitos(mensagem, padrao):
    """Pergunta a quantidade de dígitos; retorna None se o usuário cancelar."""
    resposta = questionary.text(
        mensagem,
        default=str(padrao),
        validate=validar_digitos,
    ).ask()
    return None if resposta is None else int(resposta)


# nome -> (classe, pergunta 1, padrão 1, pergunta 2, padrão 2, 2º <= 1º?)
OPERACOES = {
    "Adição": (Adicao, "Dígitos da primeira parcela:", 3, "Dígitos da segunda parcela:", 3, False),
    "Subtração": (Subtracao, "Dígitos do minuendo:", 3, "Dígitos do subtraendo:", 2, True),
    "Multiplicação": (Multiplicacao, "Dígitos do multiplicando:", 3, "Dígitos do multiplicador:", 1, False),
    "Divisão": (Divisao, "Dígitos do dividendo:", 3, "Dígitos do divisor:", 1, True),
}


def escolher_operacao():
    """Mostra o menu.

    Retorna o objeto da operação, SAIR se o usuário escolher Sair (ou
    cancelar o menu), ou None se cancelar na pergunta de dígitos
    (nesse caso o menu é exibido de novo).
    """
    escolha = questionary.select(
        "Escolha a operação:",
        choices=[*OPERACOES, SAIR],
    ).ask()
    if escolha is None or escolha == SAIR:
        return SAIR

    classe, perg1, padrao1, perg2, padrao2, segundo_menor = OPERACOES[escolha]

    while True:
        d1 = perguntar_digitos(perg1, padrao1)
        if d1 is None:
            return None
        d2 = perguntar_digitos(perg2, padrao2)
        if d2 is None:
            return None
        if segundo_menor and d2 > d1:
            print("O segundo número não pode ter mais dígitos que o primeiro. Tente de novo.")
            continue
        return classe(d1, d2)


def escolher_template(config) -> Optional[Template]:
    """Lista os templates, com o padrão já marcado. None se o usuário cancelar."""
    if len(config.templates) == 1:
        return next(iter(config.templates.values()))

    escolhas = []
    marcada = None
    for chave, template in config.templates.items():
        titulo = template.nome
        if chave == config.padrao:
            titulo += "  (padrão)"
        escolha = questionary.Choice(title=titulo, value=chave)
        escolhas.append(escolha)
        if chave == config.padrao:
            marcada = escolha

    chave = questionary.select(
        "Escolha o template:",
        choices=escolhas,
        default=marcada,
    ).ask()
    return None if chave is None else config.templates[chave]


def nome_arquivo_saida(slug, pasta):
    """Caminho 'continhas_<operacao>-AAAAMMDD_HHMM.pdf' dentro de pasta.

    Se já existir, acrescenta _2, _3... em vez de sobrescrever.
    """
    base = f"{slug}-{datetime.now().strftime('%Y%m%d_%H%M')}"
    caminho = pasta / f"{PREFIXO_ARQUIVO}_{base}.pdf"
    n = 2
    while caminho.exists():
        caminho = pasta / f"{PREFIXO_ARQUIVO}_{base}_{n}.pdf"
        n += 1
    return caminho


def gerar_folha(op, template, pasta_destino):
    if not template.caminho.exists():
        print(f"PDF do template não encontrado: {template.caminho}\n")
        return

    try:
        pasta_destino.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        print(f"Aviso: não consegui criar {pasta_destino} ({erro}); salvando na pasta atual.")
        pasta_destino = Path(".")

    caminho_saida = nome_arquivo_saida(op.slug, pasta_destino)
    try:
        gerador = GeradorFolhaMatematica(template)
        gerador.configurar_cabecalho(op.nome)
        gerador.preencher_grade(op)
        gerador.salvar(str(caminho_saida))
    except Exception as erro:
        print(f"Não foi possível gerar a folha: {erro}\n")
        return
    print(f"Folha de {op.nome.lower()} gerada: {caminho_saida}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog=NOME_APP,
        description="Gera folhas de atividades de matemática em PDF.",
    )
    parser.add_argument(
        "-c", "--config",
        help=f"arquivo de configuração (padrão: ~/.config/{NOME_APP}/config.yaml)",
    )
    args = parser.parse_args(argv)

    caminho = Path(args.config).expanduser() if args.config else caminho_config_padrao()

    if not caminho.exists():
        if args.config:
            return f"Arquivo de configuração não encontrado: {caminho}"
        criar_config_inicial(caminho)
        print(f"Criei uma configuração inicial em: {caminho}")
        print(f"Copie o PDF do seu template para {caminho.parent / PASTA_TEMPLATES / nome_pdf_template('default')}")
        print("(ou ajuste 'caminho' no arquivo) e execute novamente.")
        return 0

    try:
        config = carregar_config(caminho)
    except (ConfigErro, yaml.YAMLError) as erro:
        return f"Erro na configuração ({caminho}): {erro}"

    for aviso in config.avisos:
        print(f"Aviso: {aviso}")

    while True:
        op = escolher_operacao()
        if op == SAIR:
            print("Até logo!")
            return 0
        if op is None:  # cancelou nos dígitos: volta ao menu
            continue
        template = escolher_template(config)
        if template is None:  # cancelou a escolha do template: volta ao menu
            continue
        gerar_folha(op, template, config.pasta_destino)


if __name__ == "__main__":
    sys.exit(main())
