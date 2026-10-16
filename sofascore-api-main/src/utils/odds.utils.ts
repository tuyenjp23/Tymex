export function fractionToDecimal(fraction: string | undefined, decimalValue?: number): number | null {
  if (decimalValue) return decimalValue;
  if (!fraction || typeof fraction !== 'string') return null;
  
  const parts = fraction.split('/');
  if (parts.length === 2) {
    const num = parseFloat(parts[0] || '0');
    const den = parseFloat(parts[1] || '0');
    if (isNaN(num) || isNaN(den) || den === 0) return null;
    return (num / den) + 1;
  }
  
  const val = parseFloat(fraction);
  return isNaN(val) ? null : val;
}
