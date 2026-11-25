export default function BrandLogo({ compact = false }) {
  return (
    <span className={compact ? "brand-logo brand-logo-compact" : "brand-logo"}>
      <img src={`${import.meta.env.BASE_URL}brand/logo.png`} alt="Digna Journey" />
    </span>
  );
}
