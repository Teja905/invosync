export const CONFIDENCE_THRESHOLDS = {
  HIGH: 0.85,
  MEDIUM: 0.40,
};

export function confidenceColor(conf) {
  if (conf === null || conf === undefined) return "gray";
  if (conf >= CONFIDENCE_THRESHOLDS.HIGH) return "green";
  if (conf >= CONFIDENCE_THRESHOLDS.MEDIUM) return "yellow";
  return "red";
}

export function confidenceLabel(conf) {
  if (conf === null || conf === undefined) return "Unknown";
  if (conf >= CONFIDENCE_THRESHOLDS.HIGH) return "High";
  if (conf >= CONFIDENCE_THRESHOLDS.MEDIUM) return "Medium";
  return "Low";
}
