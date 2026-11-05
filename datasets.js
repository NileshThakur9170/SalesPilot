(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", async () => {
    const select = document.getElementById("datasetSelect");
    if (!select) return;
    try {
      const response = await fetch("/api/datasets");
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error(result.error || "Could not load datasets");
      select.innerHTML = "";
      result.datasets.forEach((dataset) => {
        const option = document.createElement("option");
        option.value = dataset.id;
        option.textContent = `${dataset.name} (${dataset.row_count} rows)`;
        option.selected = Number(dataset.id) === Number(result.current_dataset_id);
        select.appendChild(option);
      });
      select.addEventListener("change", async () => {
        const body = new URLSearchParams({dataset_id: select.value});
        const changed = await fetch("/api/datasets/select", {method: "POST", body});
        const data = await changed.json();
        if (!changed.ok || !data.success) {
          alert(data.error || "Could not switch dataset");
          return;
        }
        window.location.reload();
      });
    } catch (error) {
      console.error("Dataset selector:", error);
      select.innerHTML = '<option value="">Dataset unavailable</option>';
    }
  });
})();