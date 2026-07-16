(() => {
  const table = document.querySelector('[data-price-matrix="interactive"]');
  if (!table) return;

  const cells = Array.from(table.querySelectorAll('tbody .price-cell'));
  const columnHeaders = Array.from(table.querySelectorAll('[data-column-index]'));
  const groupHeaders = Array.from(table.querySelectorAll('[data-column-start][data-column-end]'));
  let pointerCell = null;
  let focusCell = null;

  const clearHighlight = () => {
    table.querySelectorAll('.price-row-active').forEach((element) => {
      element.classList.remove('price-row-active');
    });
    table.querySelectorAll('.price-column-active').forEach((element) => {
      element.classList.remove('price-column-active');
    });
    table.querySelectorAll('.price-cell-active').forEach((element) => {
      element.classList.remove('price-cell-active');
    });
  };

  const renderHighlight = () => {
    clearHighlight();
    const cell = pointerCell || focusCell;
    if (!cell) return;

    const row = cell.closest('tr');
    const rowHeader = row ? row.querySelector('th[scope="row"]') : null;
    const columnIndex = Number(cell.dataset.columnIndex);
    if (!row || !Number.isInteger(columnIndex)) return;

    row.classList.add('price-row-active');
    if (rowHeader) rowHeader.classList.add('price-row-active');
    cell.classList.add('price-cell-active');
    columnHeaders.forEach((element) => {
      if (Number(element.dataset.columnIndex) === columnIndex) {
        element.classList.add('price-column-active');
      }
    });
    groupHeaders.forEach((element) => {
      const start = Number(element.dataset.columnStart);
      const end = Number(element.dataset.columnEnd);
      if (start <= columnIndex && columnIndex <= end) {
        element.classList.add('price-column-active');
      }
    });
  };

  const cellFromEventTarget = (target) => {
    if (!(target instanceof Element)) return null;
    const cell = target.closest('.price-cell');
    return cell && table.contains(cell) ? cell : null;
  };

  const makeRovingTarget = (cell) => {
    cells.forEach((candidate) => {
      candidate.tabIndex = candidate === cell ? 0 : -1;
    });
  };

  table.addEventListener('pointerover', (event) => {
    const cell = cellFromEventTarget(event.target);
    if (!cell || cell === pointerCell) return;
    pointerCell = cell;
    renderHighlight();
  });

  table.addEventListener('pointerout', (event) => {
    const nextCell = cellFromEventTarget(event.relatedTarget);
    pointerCell = nextCell;
    renderHighlight();
  });

  table.addEventListener('focusin', (event) => {
    const cell = cellFromEventTarget(event.target);
    if (!cell) return;
    focusCell = cell;
    makeRovingTarget(cell);
    renderHighlight();
  });

  table.addEventListener('focusout', (event) => {
    focusCell = cellFromEventTarget(event.relatedTarget);
    renderHighlight();
  });

  table.addEventListener('click', (event) => {
    const cell = cellFromEventTarget(event.target);
    if (!cell) return;
    makeRovingTarget(cell);
    cell.focus({ preventScroll: true });
  });

  table.addEventListener('keydown', (event) => {
    const cell = cellFromEventTarget(event.target);
    if (!cell) return;
    const movement = {
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
    }[event.key];
    if (!movement) return;

    const rowIndex = Number(cell.dataset.rowIndex) + movement[0];
    const columnIndex = Number(cell.dataset.columnIndex) + movement[1];
    const target = cells.find(
      (candidate) =>
        Number(candidate.dataset.rowIndex) === rowIndex &&
        Number(candidate.dataset.columnIndex) === columnIndex,
    );
    if (!target) return;

    event.preventDefault();
    pointerCell = null;
    makeRovingTarget(target);
    target.focus({ preventScroll: false });
  });
})();
