export type FieldErrors<FieldName extends string> = Partial<
  Record<FieldName, string>
>;

export type TouchedFields<FieldName extends string> = Partial<
  Record<FieldName, boolean>
>;

const inputBaseClass =
  "w-full rounded-md border px-3 py-2 text-gray-900 transition-colors focus:outline-none focus:ring-2";
const defaultInputStateClass =
  "border-gray-300 bg-white focus:border-accent focus:ring-accent/30";
const errorInputStateClass =
  "border-red-300 bg-red-50/70 focus:border-red-400 focus:ring-red-200";
const readOnlyInputStateClass = "border-gray-300 bg-gray-100 text-gray-700";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VERIFICATION_CODE_PATTERN = /^\d{6}$/;

export function getTextInputClass(
  hasError: boolean,
  extraClass = ""
): string {
  return [inputBaseClass, hasError ? errorInputStateClass : defaultInputStateClass, extraClass]
    .filter(Boolean)
    .join(" ");
}

export function getReadOnlyInputClass(extraClass = ""): string {
  return [inputBaseClass, readOnlyInputStateClass, extraClass]
    .filter(Boolean)
    .join(" ");
}

export function getVisibleFieldError<FieldName extends string>(
  fieldName: FieldName,
  fieldErrors: FieldErrors<FieldName>,
  touchedFields: TouchedFields<FieldName>
): string {
  if (!touchedFields[fieldName]) {
    return "";
  }
  return fieldErrors[fieldName] ?? "";
}

export function touchFields<FieldName extends string>(
  current: TouchedFields<FieldName>,
  fields: readonly FieldName[]
): TouchedFields<FieldName> {
  let next = current;
  for (const field of fields) {
    if (next[field]) {
      continue;
    }
    if (next === current) {
      next = { ...current };
    }
    next[field] = true;
  }
  return next;
}

export function hasAnyFieldError<FieldName extends string>(
  fieldErrors: FieldErrors<FieldName>,
  fields?: readonly FieldName[]
): boolean {
  if (fields) {
    return fields.some((field) => Boolean(fieldErrors[field]));
  }
  return Object.values(fieldErrors).some(Boolean);
}

export function getFieldErrorId(formName: string, fieldName: string): string {
  return `${formName}-${fieldName}-error`;
}

export function isValidEmail(value: string): boolean {
  return EMAIL_PATTERN.test(value);
}

export function isValidVerificationCode(value: string): boolean {
  return VERIFICATION_CODE_PATTERN.test(value);
}
