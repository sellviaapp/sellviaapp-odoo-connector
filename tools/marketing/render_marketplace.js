const path = require("path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..", "..");
const source = path.join(__dirname, "marketplace.html");
const output = path.join(root, "sellviaapp_connector", "static", "description", "images");

const shots = [
  ["main_screenshot", "main_screenshot.png"],
  ["odoo_workspace", "01_odoo_workspace.png"],
  ["catalogue_stock", "02_catalogue_stock.png"],
  ["customers_orders", "03_customers_orders.png"],
  ["private_catalogue_api", "04_private_catalogue_api.png"],
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1680, height: 980 }, deviceScaleFactor: 1 });
  await page.goto(`file:///${source.replace(/\\/g, "/")}`, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  for (const [id, filename] of shots) {
    const locator = page.locator(`#${id}`);
    await locator.screenshot({ path: path.join(output, filename), type: "png" });
  }
  await browser.close();
  console.log(`Rendered ${shots.length} marketplace screenshots to ${output}`);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
