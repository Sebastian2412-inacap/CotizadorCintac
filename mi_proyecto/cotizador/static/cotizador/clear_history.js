(() => {
  const dialog = document.getElementById('clear-history-dialog');
  const openButton = document.querySelector('.history-clear-trigger');
  if (!(dialog instanceof HTMLDialogElement) || !openButton) return;

  const closeButtons = dialog.querySelectorAll('.history-clear-close, .history-clear-cancel');
  openButton.addEventListener('click', () => dialog.showModal());
  closeButtons.forEach((button) => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
