#! /usr/bin/env node
//
// mermaid-filter-cached.js — a caching Pandoc filter for Mermaid diagrams.
//
// This is a modified copy of the upstream `mermaid-filter` npm package
// (see build-tools/node_modules/mermaid-filter/index.js for the untouched
// original), with one thing added: a content-hash render cache. It lives
// here — under version-controlled scripts/, not inside build-tools/
// node_modules/ — because build-tools/ is entirely git-ignored and is
// wiped and recreated by `npm install` on a fresh checkout. Any edits made
// directly to the installed copy would be silently lost the next time
// dependencies are (re)installed.
//
// --- How a Pandoc JSON filter works (for readers new to Pandoc) -----------
//
// `pandoc --filter <this file>` runs this script as a subprocess. Pandoc
// parses the source document into its own internal AST, serialises that
// AST as JSON, and pipes it to this process's stdin. `pandoc-filter`'s
// `toJSONFilter(action)` helper (used at the bottom of this file) reads
// that JSON, walks every node of the AST exactly once, and calls
// `action(type, value, format, meta)` for each node. Whatever `action`
// returns replaces that node; returning null/undefined leaves it
// untouched. The (possibly modified) AST is then serialised back to JSON
// and written to stdout, where Pandoc reads it and continues the
// conversion (e.g. to LaTeX).
//
// `mermaid()` below is that `action`. It only reacts to CodeBlock nodes
// tagged with the `mermaid` class: it renders the block's text as a
// diagram image and replaces the whole CodeBlock with a Pandoc Image
// pointing at that rendered file.
//
// --- Why caching, and why it has to work this way -------------------------
//
// Rendering one diagram means running `mmdc`, which launches a full
// headless Chrome instance via Puppeteer — by far the slowest step in a
// documentation build, repeated once per diagram, every single build,
// even though the diagrams themselves rarely change.
//
// The cache is keyed purely by a hash of each diagram's own Mermaid source
// text, and stored under a directory that survives between builds. It
// deliberately does NOT live inside the per-build ".mermaid-img" output
// directories the Makefiles create (via MERMAID_FILTER_LOC): those are
// `rm -rf`'d at the start of every PDF build, so anything cached there
// would never be seen again. Instead it defaults to build-tools/
// .mermaid-cache — a location that is never deleted by the docs Makefiles'
// `clean`/`really-clean` targets — and can be overridden with
// MERMAID_FILTER_CACHE_DIR.
//
// On a cache hit, mmdc/Puppeteer is skipped entirely and the previously
// rendered file is reused directly from the cache. Because of this, the
// returned image path always points straight into the cache directory —
// there is no separate "move into MERMAID_FILTER_LOC" step as in the
// original package (nothing downstream reads the .mermaid-img directories
// besides the LaTeX compile itself, which is happy to be given an
// absolute path).
//
// Caveat: the cache key covers only the diagram source text, not
// rendering options (MERMAID_FILTER_THEME/WIDTH/FORMAT/SCALE/...). If you
// change one of those globally, previously rendered images for unchanged
// diagrams will keep being reused as-is. To force a full re-render, delete
// the cache directory (or point MERMAID_FILTER_CACHE_DIR somewhere fresh).

var fs = require('fs');
var path = require('path');
var crypto = require('crypto');
var exec = require('child_process').execSync;
var process = require('process');

// build-tools/ is a sibling of scripts/ (this file's directory), and is
// where `npm install --prefix build-tools ...` installs every dependency
// mermaid-filter itself needs, flattened to one top-level node_modules.
// Because this script does not live inside build-tools/, Node's normal
// upward node_modules lookup would not find them, so they are required by
// an explicit path instead. This must be computed before it is first used
// below (unlike function declarations, `var` assignments are not hoisted).
var BUILD_TOOLS_DIR = path.resolve(__dirname, '..', 'build-tools');
var BUILD_TOOLS_NODE_MODULES = path.join(BUILD_TOOLS_DIR, 'node_modules');

function requireFromBuildTools(name) {
    return require(path.join(BUILD_TOOLS_NODE_MODULES, name));
}

var pandoc = requireFromBuildTools('pandoc-filter');
var tmp = requireFromBuildTools('tmp');

var cmd = externalTool('mmdc');
var imgur = externalTool('imgur');
var folder = process.cwd();
// Redirect stderr to a file instead of the console: if mmdc/Puppeteer logs
// to stdout, it corrupts the JSON stream Pandoc expects back and the whole
// pandoc process hangs. errorLog is wired up in pandoc.toJSONFilter below.
var errFile = path.join(folder, "mermaid-filter.err");
var errorLog = fs.createWriteStream(errFile);

// --- Render cache -----------------------------------------------------
var cacheDir = process.env.MERMAID_FILTER_CACHE_DIR
    || path.join(BUILD_TOOLS_DIR, '.mermaid-cache');
fs.mkdirSync(cacheDir, { recursive: true });

// sha256 of the raw Mermaid source, truncated to 12 hex chars (48 bits —
// effectively collision-free for the number of diagrams in this repo).
function hashOfContent(content) {
    return crypto.createHash('sha256').update(content, 'utf8').digest('hex').slice(0, 12);
}

function mermaid(type, value, format, meta) {
    if (type != "CodeBlock") return null;
    var attrs = value[0],
        content = value[1];
    var id = attrs[0],
        classes = attrs[1];
    var options = {
        width: process.env.MERMAID_FILTER_WIDTH || 800,
        format: process.env.MERMAID_FILTER_FORMAT || 'png',
        loc: process.env.MERMAID_FILTER_LOC || 'inline',
        theme: process.env.MERMAID_FILTER_THEME || 'default',
        background: process.env.MERMAID_FILTER_BACKGROUND || 'white',
        caption: process.env.MERMAID_FILTER_CAPTION || '',
        scale: process.env.MERMAID_FILTER_SCALE || 1,
        imageClass: process.env.MERMAID_FILTER_IMAGE_CLASS || ''
    };
    var configFile = process.env.MERMAID_FILTER_MERMAID_CONFIG || path.join(folder, ".mermaid-config.json");
    var confFileOpts = ""
    if (fs.existsSync(configFile)) {
        confFileOpts += ` -c "${configFile}"`
    }
    var puppeteerConfig = process.env.MERMAID_FILTER_PUPPETEER_CONFIG || path.join(folder, ".puppeteer.json");
    var puppeteerOpts = ""
    if (fs.existsSync(puppeteerConfig)) {
        puppeteerOpts += ` -p "${puppeteerConfig}"`
    }
    var cssFile = process.env.MERMAID_FILTER_MERMAID_CSS || path.join(folder, ".mermaid.css");
    if (fs.existsSync(cssFile)) {
        confFileOpts += ` -C "${cssFile}"`
    }

    if (classes.indexOf('mermaid') < 0) return null;

    // Per-diagram attribute overrides, e.g. ```{.mermaid caption="..."}.
    attrs[2].map(item => {
        if (item.length === 1) options[item[0]] = true;
        else options[item[0]] = item[1];
    });

    // The cache key is the diagram text alone, so two identical diagrams
    // (anywhere, in any document) share one rendered file.
    var hash = hashOfContent(content);
    var cachedFile = path.join(cacheDir, `${hash}.${options.format}`);

    if (!fs.existsSync(cachedFile)) {
        // Cache miss: render via mmdc exactly as upstream mermaid-filter
        // does, then persist the result under its hash before returning.
        var tmpfileObj = tmp.fileSync();
        fs.writeFileSync(tmpfileObj.name, content);
        var renderedPath = tmpfileObj.name + "." + options.format;
        var fullCmd = `${cmd}  ${confFileOpts} ${puppeteerOpts} -w ${options.width} -s ${options.scale} -f -i "${tmpfileObj.name}" -t ${options.theme} -b ${options.background} -o "${renderedPath}"`
        exec(fullCmd);
        // The doc Makefiles build every PDF variant in parallel (make -j4)
        // from the *same* markdown sources, so identical diagrams hash
        // identically and multiple pandoc processes can race to populate
        // this same cache entry at once. Writing straight onto `cachedFile`
        // (as a plain copy) let two writers interleave into one corrupted
        // file that xelatex refused to load. A rename within the same
        // directory is atomic, so a private, uniquely-named staging file
        // is written first and swapped into place — any concurrent reader
        // sees either the old state (absent) or the complete file, never
        // a partial one, and a second racing writer's rename simply
        // replaces it with an equally valid copy.
        var stagingFile = path.join(
            cacheDir, `.${hash}.${process.pid}.${Date.now()}.tmp`
        );
        fs.copyFileSync(renderedPath, stagingFile);
        fs.renameSync(stagingFile, cachedFile);
        // Clean up the temp source/render now that the cache owns a copy —
        // otherwise these accumulate in the OS tmp dir across builds.
        fs.unlinkSync(renderedPath);
        tmpfileObj.removeCallback();
    }
    // Cache hit (or just-populated cache): fall through and reuse
    // `cachedFile` unconditionally below.

    var newPath = cachedFile;
    if (options.loc == 'inline') {
        if (options.format === 'svg') {
            var data = fs.readFileSync(cachedFile, 'utf8')
            newPath = "data:image/svg+xml;base64," + new Buffer(data).toString('base64');
        } else if (options.format === 'pdf') {
            // PDF cannot be inlined as a data URI for \includegraphics; a
            // real file path is required, so the cache file path is used
            // directly.
            newPath = cachedFile
        } else {
            var data = fs.readFileSync(cachedFile)
            newPath = 'data:image/png;base64,' + new Buffer(data).toString('base64');
        }
    } else if (options.loc === 'imgur') {
        newPath = exec(`${imgur} ${cachedFile}`)
            .toString()
            .trim()
            .replace("http://", "https://");
    }
    // else: options.loc names a plain directory (as every Makefile in this
    // repo does). Unlike upstream mermaid-filter, the rendered file is not
    // copied there — nothing downstream reads that directory's contents,
    // and `newPath` already points at a stable, absolute path in the
    // persistent cache, which is exactly what LaTeX's \includegraphics
    // needs.

    var fig = "";
    if (options.caption != "") {
        fig = "fig:";
    }

    var imageClasses = options.imageClass ? [options.imageClass] : []

    return pandoc.Para(
        [
            pandoc.Image(
                [id, imageClasses, []],
                [pandoc.Str(options.caption)],
                [newPath, fig]
            )
    ]);
}

function externalTool(command) {
    var paths = [
        path.join(BUILD_TOOLS_NODE_MODULES, ".bin", command)
    ];
    // Ability to replace path of external tool by environment variable
    // to replace `mmdc` use `MERMAID_FILTER_CMD_MMDC`
    // to replace `imgur` use `MERMAID_FILTER_CMD_IMGUR`
    var envCmdName = "MERMAID_FILTER_CMD_" + (command || "").toUpperCase().replace(/[^A-Z0-9-]/g, "_");
    var envCmd = process.env[envCmdName];
    if (envCmd) {
      paths = [envCmd];
      command = "env: " + envCmdName;  // for error message
    }
    return firstExisting(paths,
        function() {
            console.error("External tool not found: " + command);
            process.exit(1);
        });
}

function firstExisting(paths, error) {
    for (var i = 0; i < paths.length; i++) {
        if (fs.existsSync(paths[i])) return `"${paths[i]}"`;
    }
    error();
}

pandoc.toJSONFilter(function(type, value, format, meta) {
    // Redirect stderr to a globally created writeable stream
    process.stderr.write = errorLog.write.bind(errorLog);
    return mermaid(type, value, format, meta);
});
