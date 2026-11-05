(() => {
  "use strict";
  const form = document.getElementById("uploadForm");
  const fileInput = document.getElementById("fileInput");
  const status = document.getElementById("status");
  const panel = document.getElementById("previewPanel");
  const modeInputs = document.querySelectorAll('input[name="mode"]');
  const newNameWrap = document.getElementById("newNameWrap");
  const targetWrap = document.getElementById("targetWrap");
  const targetSelect = document.getElementById("targetDataset");
  const mappingGrid = document.getElementById("mappingGrid");
  const standardFields = ["Sales","Order Date","Order ID","Product Name","Quantity","Cost","Profit","Customer Name","Region","City","Category","Sub-Category","Segment","Sales Rep","Discount","Unit Price","Ship Mode"];
  let previewReady = false;
  let sourceColumns = [];

  function message(text, ok=false) { status.textContent=text; status.className=ok?"status ok":"status"; }
  async function loadDatasets() {
    const response = await fetch("/api/datasets");
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || "Could not load datasets");
    targetSelect.innerHTML = "";
    result.datasets.forEach(d => {
      const opt=document.createElement("option"); opt.value=d.id;
      opt.textContent=`${d.name} (${d.row_count} rows)`; targetSelect.appendChild(opt);
    });
  }
  function selectedMode() { return document.querySelector('input[name="mode"]:checked').value; }
  function updateMode() {
    const mode=selectedMode();
    newNameWrap.hidden=mode!=="new";
    targetWrap.hidden=mode==="new";
    document.getElementById("importBtn").textContent=mode==="replace"?"Confirm replace and import":mode==="append"?"Append rows":"Create dataset";
  }
  function renderMapping(columns, suggested) {
    sourceColumns=columns;
    mappingGrid.innerHTML="";
    standardFields.forEach(field=>{
      const wrap=document.createElement("div");wrap.className="mapping-row";
      const label=document.createElement("label");label.textContent=field;wrap.appendChild(label);
      const select=document.createElement("select");select.dataset.field=field;
      const none=document.createElement("option");none.value="";none.textContent="— Not available / don't map —";select.appendChild(none);
      columns.forEach(col=>{const opt=document.createElement("option");opt.value=col;opt.textContent=col;select.appendChild(opt);});
      if(suggested && suggested[field])select.value=suggested[field];
      wrap.appendChild(select);
      mappingGrid.appendChild(wrap);
    });
  }
  function collectMapping(){
    const mapping={};
    mappingGrid.querySelectorAll("select").forEach(sel=>{if(sel.value)mapping[sel.dataset.field]=sel.value;});
    return mapping;
  }
  modeInputs.forEach(input=>input.addEventListener("change",updateMode));
  form.addEventListener("submit", async event=>{
    event.preventDefault(); panel.hidden=true; previewReady=false; message("Reading and validating file…");
    if (!fileInput.files.length) return message("Choose a file first.");
    const body=new FormData(); body.append("file",fileInput.files[0]);
    try {
      const response=await fetch("/api/datasets/preview",{method:"POST",body});
      const result=await response.json();
      if(!response.ok||!result.success) throw new Error(result.error||"Preview failed");
      document.getElementById("previewTitle").textContent=result.filename;
      document.getElementById("previewMeta").textContent=`${result.row_count.toLocaleString()} rows · ${result.columns.length} columns · showing first ${result.preview.length} rows`;
      const table=document.getElementById("previewTable");table.innerHTML="";
      const thead=document.createElement("tr");
      result.columns.forEach(c=>{const th=document.createElement("th");th.textContent=c;thead.appendChild(th);});
      const head=document.createElement("thead");head.appendChild(thead);table.appendChild(head);
      const tbody=document.createElement("tbody");
      result.preview.forEach(row=>{const tr=document.createElement("tr");result.columns.forEach(c=>{const td=document.createElement("td");td.textContent=row[c]??"";tr.appendChild(td);});tbody.appendChild(tr);});
      table.appendChild(tbody);
      renderMapping(result.columns,result.suggested_mapping);
      await loadDatasets();
      panel.hidden=false;previewReady=true;updateMode();
      const mapped=Object.keys(result.suggested_mapping||{}).length;
      message(`File read successfully. ${mapped} likely fields detected automatically. Review the column mapping before importing.`,true);
    } catch(error){message(error.message);}
  });
  document.getElementById("importBtn").addEventListener("click",async()=>{
    if(!previewReady)return message("Preview the file before importing.");
    const mode=selectedMode();
    if(mode!=="new"&&!targetSelect.value)return message("There is no existing dataset to update. Create a new dataset first.");
    const mapping=collectMapping();
    if(!Object.keys(mapping).length)return message("Map at least one column to a business field, or choose a field such as Sales, Date, or Product.");
    const prompt=mode==="replace"
      ?"This will permanently replace all rows in the selected dataset. Other datasets will not change. Continue?"
      :mode==="append"
      ?"Append the uploaded rows to the selected dataset? Exact duplicate rows will be skipped."
      :"Create a separate dataset from this file?";
    if(!window.confirm(prompt))return;
    const payload={mode,mapping};
    if(mode==="new")payload.name=document.getElementById("datasetName").value.trim();
    else payload.dataset_id=Number(targetSelect.value);
    const button=document.getElementById("importBtn");button.disabled=true;message("Importing…");
    try{
      const response=await fetch("/api/datasets/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const result=await response.json();
      if(!response.ok||!result.success)throw new Error(result.error||"Import failed");
      let note=`Imported ${result.inserted} rows.`;
      if(result.skipped_duplicates)note+=` Skipped ${result.skipped_duplicates} exact duplicate rows.`;
      message(note+" Opening dashboard…",true);window.location.href="/dashboard";
    }catch(error){message(error.message);}
    finally{button.disabled=false;}
  });
  updateMode();
})();