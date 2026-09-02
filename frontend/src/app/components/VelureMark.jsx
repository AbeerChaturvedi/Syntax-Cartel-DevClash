/**
 * VelureMark — the angular Velure "V" logo mark.
 * Sharp two blade V with wing tips, a center notch and a pointed base.
 */
export default function VelureMark({ size = 22, color = 'currentColor', className, style }) {
  const height = Math.round((size * 112) / 120);
  return (
    <svg
      width={size}
      height={height}
      viewBox="0 0 120 112"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Velure"
      className={className}
      style={style}
    >
      <path d="M6 14 L60 110 L114 14 L74 26 L60 88 L46 26 Z" fill={color} />
    </svg>
  );
}
