
const $ = id => document.getElementById(id);

let selectedFile = null,
    translatedText = "",
    translatedFilename = "traduzido.txt";

let translationRun = 0;

let translatedBlob = null;

const fileInput = $("fileInput"),
    drop = $("dropArea");


const selectFileButton = $("selectFileButton");

const formatMenu = document.createElement("div");
formatMenu.className = "file-format-menu";
formatMenu.setAttribute("role", "group");
formatMenu.setAttribute("aria-label", "Escolha o formato do arquivo");

const formats = [
    { label: "Arquivo TXT", extension: ".txt", accept: ".txt,text/plain" },
    { label: "Documento PDF", extension: ".pdf", accept: ".pdf,application/pdf" },
    {
        label: "Documento Word (DOCX)",
        extension: ".docx",
        accept: ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
];

const formatIcons = {
    txt: `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#64748b" d="M6 2.5h8l5 5V21a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z"/>
        <path fill="#94a3b8" d="M14 2.5v5h5Z"/>
        <path fill="#fff" d="M7 11h10v1.5H7zm0 3.5h10V16H7zm0 3.5h7v1.5H7z"/>
    </svg>`,

    pdf: `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#dc2626" d="M6 2.5h8l5 5V21a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z"/>
        <path fill="#fca5a5" d="M14 2.5v5h5Z"/>
        <path fill="#fff" d="M6.5 12h11v6h-11z"/>
        <text x="12" y="16.5" font-size="5.5" font-weight="700" text-anchor="middle" fill="#dc2626">PDF</text>
    </svg>`,

    docx: `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#2563eb" d="M6 2.5h8l5 5V21a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2Z"/>
        <path fill="#93c5fd" d="M14 2.5v5h5Z"/>
        <path fill="#fff" d="M6.5 11h11v7h-11z"/>
        <path fill="#2563eb" d="m8 12.5 1 4 1.2-2.4 1.2 2.4 1-4h-1.2l-.5 2.2-.7-1.6-.7 1.6-.5-2.2Zm5.8 0h1.5a2 2 0 0 1 0 4h-1.5zm1.2 1v2h.3a1 1 0 0 0 0-2Z"/>
    </svg>`
};

formats.forEach(format => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "file-format-option";

    const icon = document.createElement("span");
    icon.className = "format-icon";
    icon.innerHTML = formatIcons[format.extension.slice(1)];

    const label = document.createElement("span");
    label.textContent = format.label;

    option.append(icon, label);

    option.addEventListener("click", () => {
        fileInput.accept = format.accept;
        fileInput.value = "";

        formatMenu.classList.remove("open");
        selectFileButton.setAttribute("aria-expanded", "false");

        fileInput.click();
    });

    formatMenu.appendChild(option);
});

const selector = document.createElement("div");
selector.className = "file-selector";

selectFileButton.parentNode.insertBefore(selector, selectFileButton);
selector.appendChild(selectFileButton);
selector.appendChild(formatMenu);

selectFileButton.setAttribute("aria-haspopup", "true");
selectFileButton.setAttribute("aria-expanded", "false");

selectFileButton.addEventListener("click", event => {
    event.stopPropagation();

    const isOpen = formatMenu.classList.toggle("open");
    selectFileButton.setAttribute("aria-expanded", String(isOpen));
});

document.addEventListener("click", event => {
    if (!selector.contains(event.target)) {
        formatMenu.classList.remove("open");
        selectFileButton.setAttribute("aria-expanded", "false");
    }
});

function resetTranslationState() {
    translatedText = "";
    translatedFilename = "traduzido.txt";
    translatedBlob = null;

    $("arrow").className = "arrow";
    $("arrow").textContent = "→";

    $("progress").style.display = "none";
    $("progressFill").style.width = "0%";

    $("progressLabel").innerHTML = "PRONTO PARA<br>TRADUZIR";

    $("preview").className = "preview empty";
    $("preview").innerHTML =
        "Seu texto traduzido aparecerá aqui.<br>Faça o upload de um arquivo e clique em traduzir.";

    $("translatedCount").textContent = "Prévia";
    $("downloadBtn").classList.remove("enabled");

    $("translateBtn").disabled = !selectedFile;
    $("translateBtn").innerHTML = 'Traduzir arquivo <span>→</span>';

    showNotice("", "");
}

function sizeLabel(n) {
    return n < 1024
        ? `${n} bytes`
        : n < 1048576
            ? `${(n / 1024).toFixed(1)} KB`
            : `${(n / 1048576).toFixed(2)} MB`
}

function chooseFile(file) {
    if (!file) return;

    const extension = file.name.split(".").pop().toLowerCase();

    if (!["txt", "pdf", "docx"].includes(extension)) {
        showNotice("Selecione um arquivo TXT, PDF ou DOCX.", "error");
        return;
    }

    if (file.size > 10 * 1024 * 1024) {
        showNotice("O arquivo excede o limite de 10 MB.", "error");
        return;
    }

    translationRun++;

    selectedFile = file;

    const fileIcon = $("fileIcon");

    fileIcon.textContent = extension.toUpperCase();
    fileIcon.classList.remove("file-icon-txt", "file-icon-pdf", "file-icon-docx");
    fileIcon.classList.add(`file-icon-${extension}`);

    $("fileName").textContent = file.name;
    $("fileSize").textContent = sizeLabel(file.size);
    $("fileMeta").style.display = "flex";
    drop.style.display = "none";
    $("originalCount").textContent = sizeLabel(file.size);

    resetTranslationState();

    $("fileName").textContent = file.name;
    $("fileSize").textContent = sizeLabel(file.size);
    $("fileMeta").style.display = "flex";
    drop.style.display = "none";
    $("originalCount").textContent = sizeLabel(file.size);

    resetTranslationState();
}

fileInput.addEventListener("change", e => chooseFile(e.target.files[0]));

$("removeFile").addEventListener("click", () => {
    translationRun++;

    selectedFile = null;
    fileInput.value = "";

    $("fileMeta").style.display = "none";
    drop.style.display = "flex";
    $("originalCount").textContent = "Nenhum arquivo";

    resetTranslationState();
});

["dragenter", "dragover"].forEach(ev =>
    drop.addEventListener(ev, e => {
        e.preventDefault();
        drop.classList.add("drag")
    })
);

["dragleave", "drop"].forEach(ev =>
    drop.addEventListener(ev, e => {
        e.preventDefault();
        drop.classList.remove("drag")
    })
);

drop.addEventListener("drop", e =>
    chooseFile(e.dataTransfer.files[0])
);

function showNotice(msg, type) {
    const n = $("notice");

    n.textContent = msg;
    n.className = "notice" + (msg ? " " + type : "")
}

$("translateBtn").addEventListener("click", async () => {
    if (!selectedFile) return;

    const runId = ++translationRun;
    const btn = $("translateBtn");

    btn.disabled = true;
    btn.textContent = "Traduzindo…";
    $("arrow").className = "arrow working";
    $("progress").style.display = "block";
    $("progressFill").style.width = "25%";
    $("progressLabel").innerHTML = "TRADUZINDO…";

    showNotice("", "");

    $("preview").className = "preview empty";
    $("preview").textContent =
        "Traduzindo seu arquivo. Isso pode levar alguns instantes.";

    try {
        const form = new FormData();

        form.append("file", selectedFile);
        form.append("source", $("source").value);
        form.append("target", $("target").value);
        form.append("protected", $("protectedTerms").value);

        $("progressFill").style.width = "55%";

        const response = await fetch("/translate", {
            method: "POST",
            body: form
        });

        if (runId !== translationRun) return;

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(
                errorData.error || "Não foi possível traduzir o arquivo."
            );
        }

        const extension = selectedFile.name.split(".").pop().toLowerCase();

        if (extension === "txt") {
            const data = await response.json();

            translatedText = data.translated;
            translatedFilename = data.filename;

            $("preview").className = "preview";
            $("preview").textContent = translatedText;

            $("translatedCount").textContent =
            `${data.translated_chars.toLocaleString("pt-BR")} caracteres`;

            $("downloadBtn").classList.add("enabled");
        } else {
            const blob = await response.blob();

            translatedText = "";
            translatedFilename =
            selectedFile.name.replace(/\.(pdf|docx)$/i, "") +
            `_${$("target").value}.${extension}`;

            // O arquivo binário fica pronto para download.
            translatedBlob = blob;

            $("preview").className = "preview empty";
            $("preview").textContent =
            `Documento ${extension.toUpperCase()} traduzido. ` +
            "Baixe o arquivo para visualizar o resultado.";

            $("translatedCount").textContent = "Documento pronto";
            $("downloadBtn").classList.add("enabled");
        }

        $("arrow").className = "arrow done";
        $("arrow").textContent = "✓";
        $("progressFill").style.width = "100%";
        $("progressLabel").innerHTML = "TRADUÇÃO<br>CONCLUÍDA";

        showNotice(
            "Arquivo traduzido com sucesso! Você já pode baixar o resultado.",
            "success"
        );
    } catch (err) {
        $("arrow").className = "arrow";
        $("arrow").textContent = "→";
        $("progressLabel").innerHTML = "ERRO NA<br>TRADUÇÃO";

        showNotice(err.message, "error");

        $("preview").className = "preview empty";
        $("preview").textContent =
            "A tradução não foi concluída. Confira a mensagem de erro e tente novamente."
    } finally {
        if (runId === translationRun) {
            btn.disabled = !selectedFile;
            btn.innerHTML = 'Traduzir arquivo <span>→</span>';

            setTimeout(() => {
                if (runId === translationRun) {
                    $("progress").style.display = "none";
                    $("progressFill").style.width = "0";
                }
            }, 1200);
        }
    }
});


$("downloadBtn").addEventListener("click", async () => {
    let blob;

    if (translatedBlob) {
        // PDF ou DOCX já traduzido.
        blob = translatedBlob;
    } else if (translatedText) {
        // TXT traduzido.
        blob = new Blob(
            ["\uFEFF", translatedText],
            { type: "text/plain;charset=utf-8" }
        );
    } else {
        return;
    }

    try {
        // Converte o arquivo para Base64 para enviá-lo ao Python.
        const reader = new FileReader();

        const base64 = await new Promise((resolve, reject) => {
            reader.onload = () => {
                const result = reader.result;
                resolve(result.substring(result.indexOf(",") + 1));
            };

            reader.onerror = () => reject(
                new Error("Não foi possível preparar o arquivo.")
            );

            reader.readAsDataURL(blob);
        });

        // No aplicativo desktop, abre a janela nativa para salvar.
        if (window.pywebview?.api?.save_file) {
            const result = await window.pywebview.api.save_file(
                translatedFilename,
                base64
            );

            if (result.cancelled) {
                return;
            }

            if (!result.success) {
                throw new Error(
                    result.error || "Não foi possível salvar o arquivo."
                );
            }

            showNotice("Arquivo salvo em: " + result.path, "success");
            return;
        }

        // Alternativa para quando o projeto é aberto no navegador.
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");

        a.href = url;
        a.download = translatedFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();

        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
        showNotice(error.message, "error");
    }
});

function openSide() {
    $("sidebar").classList.add("open");
    $("scrim").classList.add("open")
}

function closeSide() {
    $("sidebar").classList.remove("open");
    $("scrim").classList.remove("open")
}

$("openSidebar").addEventListener("click", openSide);
$("closeSidebar").addEventListener("click", closeSide);
$("scrim").addEventListener("click", closeSide);

let glossaryEntries = [];

// Será preenchido pelo Flask no index.html.
const languageNames = window.sourceLanguages || {};

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, c => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    }[c]))
}

function renderGlossary() {
    const list = $("glossaryList");

    if (!glossaryEntries.length) {
        list.innerHTML =
            '<div class="empty-glossary">Nenhuma regra personalizada ainda.</div>';
        return
    }

    list.innerHTML = glossaryEntries.map((entry, index) =>
        `<div class="glossary-item">
            <div class="glossary-pair">
                <strong>${escapeHtml(entry.source)} → ${escapeHtml(entry.translation)}</strong>
                <div class="glossary-meta">${
                    escapeHtml(
                        entry.source_lang === '*'
                            ? 'Qualquer origem'
                            : languageNames[entry.source_lang] || entry.source_lang
                    )
                } → ${
                    escapeHtml(
                        entry.target_lang === '*'
                            ? 'Qualquer destino'
                            : languageNames[entry.target_lang] || entry.target_lang
                    )
                }</div>
            </div>
            <button class="delete-rule" data-delete-rule="${index}" title="Remover regra">×</button>
        </div>`
    ).join('');

    list.querySelectorAll('[data-delete-rule]').forEach(button =>
        button.addEventListener('click', async () => {
            glossaryEntries.splice(
                Number(button.dataset.deleteRule),
                1
            );

            renderGlossary();

            await persistSettings(false)
        })
    )
}

async function persistSettings(showMessage = true) {
    const response = await fetch('/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            protected: $("protectedTerms").value,
            glossary: glossaryEntries
        })
    });

    if (!response.ok) {
        throw new Error('Não foi possível salvar as preferências.')
    }

    if (showMessage) {
        $("savedNote").textContent =
            'Preferências salvas no computador.';

        setTimeout(
            () => $("savedNote").textContent = '',
            2500
        )
    }
}

async function loadSettings() {
    try {
        const response = await fetch('/settings');
        const data = await response.json();

        $("protectedTerms").value = data.protected || '';

        glossaryEntries = Array.isArray(data.glossary)
            ? data.glossary
            : [];

        renderGlossary()
    } catch (error) {
        $("glossaryList").innerHTML =
            '<div class="empty-glossary">Não foi possível carregar o dicionário local.</div>'
    }
}

$("addGlossary").addEventListener('click', async () => {
    const original = $("glossarySource").value.trim();
    const translation = $("glossaryTranslation").value.trim();

    if (!original || !translation) {
        $("savedNote").textContent =
            'Preencha a palavra original e a tradução.';
        return
    }

    const sourceCode = $("source").value;
    const targetCode = $("target").value;

    const entry = {
        source: original,
        translation,
        source_lang: sourceCode === 'auto' ? '*' : sourceCode,
        target_lang: targetCode
    };

    const duplicate = glossaryEntries.findIndex(e =>
        e.source.toLocaleLowerCase() === original.toLocaleLowerCase() &&
        e.source_lang === entry.source_lang &&
        e.target_lang === entry.target_lang
    );

    if (duplicate >= 0) {
        glossaryEntries[duplicate] = entry
    } else {
        glossaryEntries.push(entry)
    }

    $("glossarySource").value = '';
    $("glossaryTranslation").value = '';

    renderGlossary();

    try {
        await persistSettings(false);

        $("savedNote").textContent =
            'Regra adicionada e salva no computador.';

        setTimeout(
            () => $("savedNote").textContent = '',
            2500
        )
    } catch (error) {
        showNotice(error.message, 'error')
    }
});

$("downloadModel").addEventListener('click', async () => {
    const button = $("downloadModel");
    const note = $("modelNote");

    const sourceCode = $("source").value;
    const targetCode = $("target").value;

    if (sourceCode === 'auto') {
        note.textContent =
            'Selecione um idioma de origem específico antes de baixar o modelo.';
        return
    }

    if (sourceCode === targetCode) {
        note.textContent = 'Escolha idiomas diferentes.';
        return
    }

    button.disabled = true;
    button.textContent = 'Baixando e instalando…';

    note.textContent =
        'Consultando catálogo. Isso pode demorar e exige internet.';

    try {
        const response = await fetch('/models/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source: sourceCode,
                target: targetCode
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error || 'Falha ao instalar o modelo.'
            )
        }

        note.textContent = data.message
    } catch (error) {
        note.textContent = error.message
    } finally {
        button.disabled = false;
        button.textContent =
            'Baixar modelo dos idiomas selecionados'
    }
});

$("saveTerms").addEventListener('click', async () => {
    try {
        await persistSettings(true);
        closeSide()
    } catch (error) {
        $("savedNote").textContent = error.message
    }
});

loadSettings();
