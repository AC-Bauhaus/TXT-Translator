# TXT Tradutor Offline — aplicativo híbrido multiplataforma

A interface continua em HTML/CSS/JavaScript, mas roda em uma janela de aplicativo com `pywebview` e um backend Python local. A tradução usa **Argos Translate**, com modelos de tradução executados no próprio computador. Durante a tradução, o aplicativo não envia seu texto para sites ou APIs de terceiros.

## Importante sobre funcionar sem internet

O motor é local, mas os modelos de idioma precisam estar instalados. A primeira instalação de um modelo pode ser feita com internet (`--download`) ou transferindo um arquivo `.argosmodel` de outro computador (`--install`). Depois que o modelo está instalado, a tradução funciona sem internet. É necessário instalar o modelo para cada par de idiomas que você pretende usar; o catálogo pode não ter todos os pares disponíveis.

## Executar no Garuda/Arch Linux

```bash
sudo pacman -S --needed python python-pip python-virtualenv base-devel
cd tradutor_txt
python -m venv .venv
source .venv/bin/activate.fish  # Fish; em Bash use: source .venv/bin/activate
python -m pip install -r requirements.txt
python desktop.py
```

Se a janela nativa não abrir por falta de bibliotecas gráficas do `pywebview`, o programa pode abrir no navegador padrão. O backend ainda roda localmente.

## Instalar um modelo (só na primeira vez)

Exemplo para inglês -> português:

```bash
.venv/bin/python gerenciar_modelos.py --download en pt
```

Exemplo português -> inglês:

```bash
.venv/bin/python gerenciar_modelos.py --download pt en
```

Liste os idiomas instalados:

```bash
.venv/bin/python gerenciar_modelos.py --list
```

Para instalar sem internet, copie um arquivo `.argosmodel` para o computador e rode:

```bash
.venv/bin/python gerenciar_modelos.py --install /caminho/para/modelo.argosmodel
```

## Criar um executável

O PyInstaller gera executáveis para o sistema em que é executado; não existe um único executável nativo universal para Windows, Linux e macOS. Gere uma compilação em cada sistema operacional.

```bash
python -m PyInstaller --noconfirm --clean --windowed --name TXTTradutorOffline --add-data "templates:templates" desktop.py
```

No Windows, o separador de `--add-data` é ponto e vírgula:

```powershell
python -m PyInstaller --noconfirm --clean --windowed --name TXTTradutorOffline --add-data "templates;templates" desktop.py
```

O resultado fica em `dist/`. O computador de destino também precisa ter os modelos Argos instalados. Para distribuir uma cópia realmente pronta para uso offline, distribua junto os arquivos `.argosmodel` licenciados e inclua o passo de instalação local no instalador.

## Uso

1. Inicie `desktop.py` ou o executável.
2. Selecione um arquivo `.txt` em UTF-8.
3. Escolha os idiomas e clique em **Traduzir arquivo**.
4. Termos na lateral são protegidos para permanecerem no original.
5. Baixe o arquivo traduzido.

Os arquivos são processados localmente. O limite de upload é 10 MB.


### Garuda Linux / Arch Linux: janela nativa (opcional)

Se o pywebview informar que não encontrou GTK ou Qt, o programa abrirá a interface
no navegador padrão automaticamente. A tradução continua local; o navegador acessa
apenas o servidor executado no próprio computador (`127.0.0.1`).

Para tentar habilitar a janela nativa no Garuda, instale um backend gráfico do sistema
e recrie o ambiente virtual para que ele possa enxergar os módulos Python do sistema.
Os nomes dos pacotes podem variar conforme os repositórios disponíveis:

```fish
sudo pacman -S python-gobject gtk3 webkit2gtk
```

Depois, feche o programa e recrie o ambiente virtual:

```fish
rm -rf .venv
python -m venv --system-site-packages .venv
source .venv/bin/activate.fish
python -m pip install -r requirements.txt
.venv/bin/python desktop.py
```

Se o comando do `pacman` disser que `webkit2gtk` não existe, não force a instalação:
use o fallback do navegador ou consulte o nome atual do pacote WebKitGTK nos repositórios
do Garuda. A primeira instalação dos pacotes e dos modelos de tradução exige internet;
a tradução depois de instalar os modelos funciona offline.


## Instalar como aplicativo com ícone no Garuda/Linux

Com a pasta do projeto extraída e as dependências instaladas, execute uma vez:

```bash
chmod +x instalar_aplicativo_linux.sh
./instalar_aplicativo_linux.sh
```

Isso cria o atalho **TXT Tradutor Offline** no menu de aplicativos, com ícone. O atalho inicia o servidor apenas em `127.0.0.1` e abre a interface no navegador se a janela nativa não estiver disponível. Não é necessário instalar WebKitGTK para usar o fallback do navegador.

## Dicionário personalizado

Abra o botão de preferências no canto superior e use **Dicionário personalizado**. Informe a palavra original e a tradução preferida, depois clique em adicionar. Exemplo com Inglês → Português:

- Original: `Word`
- Tradução: `Palavra`

A regra substitui todas as ocorrências da palavra completa, sem trocar trechos de palavras maiores (por exemplo, `word` não altera `sword`). As regras são salvas em um arquivo de configurações do usuário e continuam disponíveis depois de fechar/reabrir o aplicativo. A origem/destino da regra corresponde aos idiomas selecionados no momento em que ela é criada; se a origem estiver em detecção automática, a regra vale para qualquer origem e para o destino selecionado.

As palavras do dicionário personalizado têm prioridade sobre a lista de palavras protegidas. Isso permite que uma regra como `Word → Palavra` seja aplicada mesmo que `Word` também esteja na lista de termos protegidos.

## Mais idiomas e modelos

A lista de idiomas foi ampliada. No painel de preferências, a seção **Biblioteca de modelos offline** permite baixar e instalar o modelo do par de idiomas selecionado. Esse passo requer internet apenas para consultar o catálogo e baixar o modelo. Depois da instalação, a tradução é local. Nem todo par tem um modelo direto disponível; se isso acontecer, tente um par via inglês ou instale um arquivo `.argosmodel` compatível. O catálogo e os pares disponíveis podem mudar com o tempo.

O Argos Translate usa modelos locais `.argosmodel` e pode usar idiomas intermediários quando os modelos necessários estão instalados. Consulte a [documentação oficial](https://argos-translate.readthedocs.io/en/stable/index.html) para detalhes.
