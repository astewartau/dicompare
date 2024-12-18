let pyodide;
let tagInputfmGenRef_acquisitionFields, tagInputfmGenRef_referenceFields;
//const dicompare_url = "http://localhost:8000/dist/dicompare-0.1.10-py3-none-any.whl";
//const valid_fields_url = "http://localhost:8000/valid_fields.json";
const dicompare_url = "dicompare==0.1.10"
const valid_fields_url = "https://raw.githubusercontent.com/astewartau/dicompare/v0.1.10/valid_fields.json";

async function initTagify() {
    // Fetch the list of valid fields for Tagify
    const response = await fetch(valid_fields_url);
    const validFields = await response.json();

    // Set up acquisition fields
    tagInputfmGenRef_acquisitionFields = new Tagify(document.getElementById("fmGenRef_acquisitionFields"), {
        whitelist: validFields,
        enforceWhitelist: true,
        dropdown: { enabled: 0, position: "all" },
    });

    // Add default values to Acquisition Fields
    if (tagInputfmGenRef_acquisitionFields.value.length === 0) {
        tagInputfmGenRef_acquisitionFields.addTags(["ProtocolName"]);
    }

    // Set up reference fields
    tagInputfmGenRef_referenceFields = new Tagify(document.getElementById("fmGenRef_referenceFields"), {
        whitelist: validFields,
        enforceWhitelist: true,
        dropdown: { enabled: 0, position: "all" },
    });
}

async function initPyodide() {
    const pyodideInstance = await loadPyodide(); // Use the library's `loadPyodide`
    await pyodideInstance.loadPackage("micropip");

    // Install `dicompare` using micropip
    await pyodideInstance.runPythonAsync(`
          import micropip
          await micropip.install("${dicompare_url}")
      `);

    return pyodideInstance;
}

async function loadDICOMs(inputId) {
    const inputElement = document.getElementById(inputId);
    const files = inputElement.files;
    const dicomFiles = {};

    for (let file of files) {
        if (file.name.endsWith(".dcm") || file.name.endsWith(".IMA")) {
            const slice = file.slice(0, 4096);
            const fileContent = new Uint8Array(await slice.arrayBuffer());
            dicomFiles[file.webkitRelativePath] = fileContent;
        }
    }

    return dicomFiles;
}

tippy('.info-icon');
initTagify();

