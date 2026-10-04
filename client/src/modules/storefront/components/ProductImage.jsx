import { PrivateImage } from "../../../components/PrivateImage";
import amayaMicroUsbImage from "../../../assets/images/stock/Amaya Normal Charging USB Cable.png";

const amayaMicroUsbSku = "AMAYA-AM-M01-MICRO-B-WHT-1M2";
const amayaMicroUsbAlt =
  "Amaya AM-M01 Type-B Micro-USB white 1.2m 3.1A charging cable";

export function ProductImage({ product, large = false }) {
  const isAmayaMicroUsb = product.sku === amayaMicroUsbSku;
  const image =
    product.images?.find((image) => image.url) ||
    (isAmayaMicroUsb
      ? { url: amayaMicroUsbImage, alt: amayaMicroUsbAlt }
      : null);
  return (
    <div className={`productImage${large ? " large" : ""}`}>
      {image ? (
        <PrivateImage
          src={image.url}
          alt={
            isAmayaMicroUsb
              ? amayaMicroUsbAlt
              : product.display_name || image.alt || product.product_name
          }
        />
      ) : (
        (product.product_name || product.display_name || "?")[0]
      )}
    </div>
  );
}
