package main

type Calculator struct{}

func Add(a int, b int) int {
	return a + b
}

func (c Calculator) Subtract(a int, b int) int {
	return a - b
}
