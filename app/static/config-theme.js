// Neo-brutalist CodeMirror theme for the config editor. Colours are the site's
// CSS variables, so light/dark mode follows style.css automatically.
import { EditorView, HighlightStyle, syntaxHighlighting, tags as t } from "/static/cm.js";

const tint = (color, percent) => `color-mix(in srgb, var(${color}) ${percent}%, transparent)`;

// Flat, bordered box shared by tooltips and the autocomplete popup.
const box = {
	background: "var(--bg)",
	color: "var(--text)",
	border: "3px solid var(--border)",
	borderRadius: "var(--radius)",
	boxShadow: "4px 4px 0 var(--border)",
};

// Undo style.css's global input/button rules inside editor panels.
const bareInput = {
	padding: "0",
	background: "transparent",
	color: "inherit",
	font: "inherit",
	border: "none",
	boxShadow: "none",
	transform: "none",
};

const editorTheme = EditorView.theme({
	"&": {
		height: "70vh",
		color: "var(--text)",
		background: "var(--bg)",
	},
	"&.cm-focused": { outline: "none" },
	".cm-scroller": { fontFamily: "'Space Mono', monospace", lineHeight: "1.6" },
	".cm-content": { padding: "12px 0", caretColor: "var(--text)" },
	".cm-line": { padding: "0 16px" },

	// Gutter: a surface-coloured strip with a hard divider, like the card header rule
	".cm-gutters": {
		background: "var(--surface)",
		color: "var(--text-muted)",
		border: "none",
		borderRight: "3px solid var(--border)",
		fontWeight: "bold",
	},
	".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 14px" },
	".cm-activeLineGutter": { background: "var(--surface-hover)", color: "var(--text)" },
	".cm-foldGutter .cm-gutterElement": { padding: "0 4px", cursor: "pointer" },

	// Active line is translucent so the selection layer beneath it stays visible
	".cm-activeLine": { background: tint("--surface", 35) },
	".cm-cursor, .cm-dropCursor": { borderLeft: "2px solid var(--text)" },
	"&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
		{ background: tint("--primary", 28) },
	"&.cm-focused .cm-matchingBracket": {
		background: tint("--primary", 20),
		outline: "2px solid var(--primary)",
	},
	"&.cm-focused .cm-nonmatchingBracket": { outline: "2px solid var(--danger)" },
	".cm-searchMatch": { background: tint("--surface", 80), outline: "2px solid var(--border)" },
	".cm-searchMatch.cm-searchMatch-selected": { background: tint("--primary", 35) },
	".cm-selectionMatch": { background: tint("--surface", 60) },
	".cm-foldPlaceholder": {
		background: "var(--surface)",
		color: "var(--text)",
		border: "2px solid var(--border)",
		borderRadius: "var(--radius)",
		padding: "0 6px",
	},

	// Tooltips and autocomplete
	".cm-tooltip": { ...box, fontFamily: "'Space Mono', monospace" },
	".cm-tooltip-autocomplete > ul": { fontFamily: "inherit", maxHeight: "16em" },
	".cm-tooltip-autocomplete > ul > li": { padding: "4px 12px 4px 8px" },
	".cm-tooltip-autocomplete > ul > li[aria-selected]": {
		background: "var(--primary)",
		color: "var(--on-primary)",
	},
	".cm-completionDetail": { color: "var(--text-muted)", fontStyle: "normal", marginLeft: "1em" },
	"li[aria-selected] .cm-completionDetail": { color: "inherit" },
	".cm-completionMatchedText": { textDecoration: "none", fontWeight: "bold" },
	".cm-tooltip.cm-completionInfo": { ...box, padding: "6px 10px" },
	".cm-diagnostic": { padding: "6px 10px" },
	".cm-diagnostic-error": { borderLeft: "5px solid var(--danger)" },

	// Panels (search, vim command line) under/over the text
	".cm-panels": { background: "var(--surface)", color: "var(--text)" },
	".cm-panels.cm-panels-top": { borderBottom: "3px solid var(--border)" },
	".cm-panels.cm-panels-bottom": { borderTop: "3px solid var(--border)" },
	".cm-panel.cm-search": { padding: "8px 12px", fontFamily: "inherit" },
	".cm-panel.cm-search label": { fontSize: "0.85rem", fontWeight: "bold" },
	".cm-panel.cm-search input[type=checkbox]": {
		...bareInput,
		accentColor: "var(--primary)",
		verticalAlign: "middle",
	},
	".cm-textfield": {
		padding: "4px 8px",
		background: "var(--bg)",
		color: "var(--text)",
		font: "inherit",
		border: "2px solid var(--border)",
		borderRadius: "var(--radius)",
		boxShadow: "2px 2px 0 var(--border)",
		transform: "none",
	},
	".cm-textfield:focus": { borderColor: "var(--primary)" },
	".cm-button": {
		padding: "4px 10px",
		background: "var(--bg)",
		backgroundImage: "none",
		color: "var(--text)",
		font: "inherit",
		fontSize: "0.85rem",
		border: "2px solid var(--border)",
		borderRadius: "var(--radius)",
		boxShadow: "2px 2px 0 var(--border)",
	},
	".cm-button:active": { backgroundImage: "none", transform: "translate(1px, 1px)", boxShadow: "none" },
	".cm-panel button[name=close]": {
		...bareInput,
		padding: "0 4px",
		fontSize: "1.2rem",
		cursor: "pointer",
	},

	// Vim mode: its fat cursor lives in an EditorView.theme too, so the extra
	// .cm-editor class keeps these ahead of it on specificity.
	"&.cm-editor .cm-fat-cursor": {
		background: "var(--primary)",
		color: "var(--on-primary)",
		outline: "none",
	},
	"&.cm-editor:not(.cm-focused) .cm-fat-cursor": {
		background: "none",
		outline: "2px solid var(--primary)",
	},
	".cm-vim-panel": { padding: "4px 12px", fontFamily: "inherit", fontWeight: "bold" },
	".cm-vim-panel input": bareInput,
});

// Plain YAML values (yes, 7734, /music) are all `content` in @lezer/yaml, so
// they keep the default text colour; only the tags below get colour.
const yamlHighlight = HighlightStyle.define([
	{ tag: t.propertyName, color: "var(--primary)", fontWeight: "bold" },
	{ tag: t.string, color: "var(--success)" },
	{ tag: t.special(t.string), color: "var(--success)", fontWeight: "bold" },
	{ tag: t.comment, color: "var(--text-muted)", fontStyle: "italic" },
	{ tag: [t.labelName, t.typeName], color: "var(--danger)" },
	{ tag: [t.separator, t.punctuation, t.squareBracket, t.brace], color: "var(--text-muted)" },
	{ tag: [t.keyword, t.meta], color: "var(--text-muted)", fontWeight: "bold" },
]);

export const configTheme = [editorTheme, syntaxHighlighting(yamlHighlight)];
