import { EditorView, basicSetup, indentWithTab, keymap, yaml } from "/static/cm.js";
import { configTheme } from "/static/config-theme.js";

const form = document.getElementById("config-form");
const textarea = form.elements.yaml_text;
const saveButton = form.querySelector("button[type=submit]");
const bar = form.querySelector(".config-bar");
const editorElement = document.getElementById("config-editor");
// Browsers can't detect a physical keyboard, so "has a mouse or trackpad" is
// the proxy
const hasFinePointer = matchMedia("(any-pointer: fine)").matches;
const keymapExtensions =
	editorElement.dataset.keymap === "vim" && hasFinePointer ? await vimMode() : [];

let saved = textarea.value;   // what's on disk
let submitted = saved;        // what the in-flight save sent

async function vimMode() {
	try {
		const { vim, Vim } = await import("/static/cm-vim.js");
		Vim.defineEx("write", "w", () => form.requestSubmit());
		return [vim({ status: true })];
	} catch (error) {
		console.warn("Vim mode failed to load; using default keys.", error);
		return [];
	}
}

export const view = new EditorView({
	doc: saved,
	parent: editorElement,
	extensions: [
		...keymapExtensions,
		keymap.of([
			{ key: "Mod-s", preventDefault: true, run: () => (form.requestSubmit(), true) },
			// Tab/Shift-Tab indent by indentUnit (two spaces; YAML forbids tabs).
			// Esc then Tab still moves focus out, for keyboard-only users.
			indentWithTab,
		]),
		basicSetup,
		yaml(),
		configTheme,
		EditorView.updateListener.of((update) => update.docChanged && sync()),
	],
});
textarea.hidden = true;
form.classList.remove("is-loading");
if (hasFinePointer) view.focus();

function sync() {
	textarea.value = view.state.doc.toString();
	saveButton.disabled = textarea.value === saved;
}

form.addEventListener("submit", () => (submitted = textarea.value));

// htmx replaces #config-status after a save. Watching the DOM, rather than
// htmx events, keeps this independent of htmx 4's event names.
new MutationObserver(() => {
	if (bar.querySelector("#config-status[data-saved]")) {
		saved = submitted;
		sync();
	}
}).observe(bar, { childList: true, subtree: true });
