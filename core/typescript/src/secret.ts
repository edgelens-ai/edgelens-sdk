/**
 * Secrets stay readable by name but out of printed and serialised output.
 *
 * The secret is a non-enumerable property, which `JSON.stringify`, object
 * spread, `Object.keys` and a default `console.log` skip. Node's inspector
 * shows non-enumerable properties when asked to (`showHidden`, which `%o`
 * turns on), so the object also gets a `util.inspect.custom` hook that
 * prints only its enumerable properties. Reading the property directly
 * (`creds.password`) still returns the value.
 */

const INSPECT = Symbol.for("nodejs.util.inspect.custom");

type Inspect = (value: unknown, options: object) => string;

function hideFromInspect(target: object): void {
  if (Object.prototype.hasOwnProperty.call(target, INSPECT)) return;
  Object.defineProperty(target, INSPECT, {
    value(this: object, _depth: number, options: object, inspect: Inspect): string {
      const visible = Object.create(Object.getPrototypeOf(this)) as object;
      return inspect(Object.assign(visible, this), options);
    },
    enumerable: false,
  });
}

/** Define `key` on `target` as a read-only property that no printout shows. */
export function defineSecret<T extends object>(target: T, key: PropertyKey, value: unknown): void {
  Object.defineProperty(target, key, {
    value,
    enumerable: false,
    writable: false,
    configurable: false,
  });
  hideFromInspect(target);
}

/** A shallow copy of `obj` whose `key` is a secret (see `defineSecret`). */
export function withSecret<T extends object, K extends keyof T>(obj: T, key: K): T {
  const copy = { ...obj };
  delete copy[key];
  defineSecret(copy, key, obj[key]);
  return copy;
}
