(() => {
  const trigger = document.querySelector(".profile-avatar-trigger");
  const menu = document.querySelector("#profile-avatar-menu");
  const fileInput = document.querySelector("#profile-avatar-input");
  const clearInput = document.querySelector("#avatar-clear");
  const panel = document.querySelector(".profile-panel");
  const details = document.querySelector("#profile-details");
  const editForm = document.querySelector("#profile-edit-form");
  const editToggle = document.querySelector(".profile-edit-toggle");

  if (!trigger || !menu || !fileInput || !clearInput || !panel || !details || !editForm || !editToggle) return;

  const setEditMode = (editing) => {
    panel.classList.toggle("is-editing", editing);
    details.hidden = editing;
    editForm.hidden = !editing;
    editToggle.setAttribute("aria-expanded", String(editing));
  };

  editToggle.addEventListener("click", () => setEditMode(true));
  editForm.querySelector("[data-profile-cancel]").addEventListener("click", () => window.location.reload());

  const closeMenu = () => {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  };

  trigger.addEventListener("click", () => {
    const isExpanded = trigger.getAttribute("aria-expanded") === "true";
    menu.hidden = isExpanded;
    trigger.setAttribute("aria-expanded", String(!isExpanded));
  });

  menu.querySelector("[data-avatar-edit]").addEventListener("click", () => {
    setEditMode(true);
    closeMenu();
    fileInput.click();
  });

  const image = trigger.querySelector("img");
  const placeholder = trigger.querySelector(".profile-avatar-placeholder");
  menu.querySelector("[data-avatar-remove]")?.addEventListener("click", () => {
    setEditMode(true);
    clearInput.checked = true;
    fileInput.value = "";
    image.hidden = true;
    placeholder.hidden = false;
    closeMenu();
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) return;

    clearInput.checked = false;
    image.src = URL.createObjectURL(file);
    image.hidden = false;
    placeholder.hidden = true;
    closeMenu();
  });

  document.addEventListener("click", (event) => {
    if (!trigger.contains(event.target) && !menu.contains(event.target)) closeMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
})();
