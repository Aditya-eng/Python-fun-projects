try:
    n = 10/0
    print(n)
except ZeroDivisionError:
    print("Error")
finally:
    print("Error not consumed")
