import { useEffect, useState } from "react";

export function DisplayImageInput({ file, onChange, required = false, existingUrl = "" }) {
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!file) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const choose = (event) => {
    const image = event.target.files?.[0];
    if (!image) return;
    if (!/^image\/(jpeg|png|webp)$/.test(image.type) || image.size > 15 * 1024 * 1024) {
      setError("Choose a JPEG, PNG or WebP photograph smaller than 15 MB.");
      event.target.value = "";
      return;
    }
    setError(""); onChange(image);
  };
  return <fieldset>
    <legend>Product display image{required ? " (required)" : ""}</legend>
    <p>Photograph this exact item alone. This is the customer display photo, separate from the supplier receipt and shelf placement.</p>
    <label>Upload from storage<input type="file" accept="image/jpeg,image/png,image/webp" onChange={choose} /></label>
    <label>Take photo<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={choose} /></label>
    {error && <p role="alert">{error}</p>}
    {(preview || existingUrl) && <img src={preview || existingUrl} alt="Product display image preview" style={{ maxWidth: "100%", maxHeight: 240, objectFit: "contain" }} />}
    {file && <button type="button" className="secondary" onClick={() => onChange(null)}>Remove selected photo</button>}
  </fieldset>;
}
