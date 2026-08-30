/** Mirrors the backend's calculate_emi (services/finance/loans.py) so the
 * Loans form can suggest an EMI as the user types, before submitting. */
export function calculateEmi(principal: number, annualRate: number, tenureMonths: number): number {
  const monthlyRate = annualRate / 100 / 12
  if (tenureMonths <= 0) return 0
  if (monthlyRate === 0) return principal / tenureMonths
  const factor = (1 + monthlyRate) ** tenureMonths
  return (principal * monthlyRate * factor) / (factor - 1)
}
