// The only script in the product: it shows what a resolution would cost before
// the reviewer commits to it. It never sends anything and never writes a price
// anywhere — the figure it draws is thrown away on submit and the server
// recomputes it from the contract.

const money = new Intl.NumberFormat("en-AU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

for (const select of document.querySelectorAll(".resolve select")) {
  const output = select.parentElement.querySelector(".preview");
  const quantity = Number(select.dataset.quantity);

  select.addEventListener("change", () => {
    const price = select.selectedOptions[0].dataset.price;
    if (!price) {
      output.hidden = true;
      return;
    }
    output.hidden = false;
    output.textContent = `${quantity} × ${money.format(price)} = ${money.format(price * quantity)}`;
  });
}
