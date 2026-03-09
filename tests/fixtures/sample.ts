export function greet(name: string): string {
  const message = `Hello, ${name}!`;
  console.log(message);
  return message;
}

const double = (x: number): number => {
  return x * 2;
};

class Calculator {
  private value: number;

  constructor(initial: number) {
    this.value = initial;
  }

  add(n: number): number {
    this.value += n;
    return this.value;
  }

  subtract(n: number): number {
    this.value -= n;
    return this.value;
  }
}
