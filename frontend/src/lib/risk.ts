import type { RiskLevel } from './api'

export const RISK_LEVELS: RiskLevel[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export const RISK_LABEL: Record<RiskLevel, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No Travel',
}

/** RGB, so the same colours can be used by CSS and by deck.gl layers. */
export const RISK_RGB: Record<RiskLevel, [number, number, number]> = {
  low: [46, 157, 91],
  moderate: [230, 180, 23],
  high: [240, 124, 30],
  severe: [215, 48, 31],
  no_travel: [106, 27, 154],
}

export function riskCss(level: RiskLevel): string {
  return `rgb(${RISK_RGB[level].join(',')})`
}
