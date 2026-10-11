// Drop-zone component for the import work area (imports/work_idle.html):
// x-data="dropZone(url, maxBytes)". Uploads go through XHR rather than htmx,
// because htmx 4 sends with fetch, which can't report upload progress.
function dropZone(url, maxBytes) {
	return {
		over: false,
		busy: false,
		progress: 0,
		message: "",

		leave(event) {
			// dragleave also fires when moving onto a child of the zone
			if (!event.currentTarget.contains(event.relatedTarget)) this.over = false;
		},

		async drop(event) {
			this.over = false;
			this.upload(await droppedFiles(event.dataTransfer));
		},

		pick(event) {
			const input = event.target;
			this.upload([...input.files].map((file) => [file, file.webkitRelativePath || file.name]));
			input.value = "";
		},

		upload(pairs) {
			if (!pairs.length || this.busy) return;
			const total = pairs.reduce((sum, [file]) => sum + file.size, 0);
			if (total > maxBytes) {
				this.message = `${toMB(total)} MB is over the ${toMB(maxBytes)} MB limit`;
				return;
			}

			const form = new FormData();
			for (const [file, path] of pairs) {
				form.append("files", file);
				form.append("paths", path);
			}

			this.busy = true;
			this.progress = 0;
			this.message = "";

			const xhr = new XMLHttpRequest();
			xhr.open("POST", url);
			xhr.upload.onprogress = (event) => {
				if (event.lengthComputable) this.progress = event.loaded / event.total;
			};
			xhr.onload = () => {
				if (xhr.status !== 200) return this.fail(`Upload failed (${xhr.status})`);
				const area = document.getElementById("work-area");
				area.innerHTML = xhr.responseText;
				htmx.process(area);
			};
			xhr.onerror = () => this.fail("Upload failed");
			xhr.send(form);
		},

		fail(message) {
			this.busy = false;
			this.message = message;
		},
	};
}

const toMB = (bytes) => Math.ceil(bytes / 1048576);

// [file, relative path] pairs for everything dropped, walking into folders.
async function droppedFiles(dataTransfer) {
	// Take every entry before the first await: the DataTransfer is emptied after that.
	const entries = [...dataTransfer.items]
		.map((item) => item.webkitGetAsEntry?.())
		.filter(Boolean);
	const out = [];
	for (const entry of entries) await walk(entry, out);
	return out;
}

async function walk(entry, out) {
	if (entry.isFile) {
		const file = await new Promise((ok, fail) => entry.file(ok, fail));
		out.push([file, entry.fullPath.replace(/^\//, "")]);
	} else if (entry.isDirectory) {
		for (const child of await readAll(entry)) await walk(child, out);
	}
}

// readEntries returns at most ~100 entries per call; keep calling until it's empty.
async function readAll(dir) {
	const reader = dir.createReader();
	const all = [];
	for (;;) {
		const batch = await new Promise((ok, fail) => reader.readEntries(ok, fail));
		if (!batch.length) return all;
		all.push(...batch);
	}
}
