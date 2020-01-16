try:
          n = 10/0
          print(n)
except ZeroDivisionError as error, NameError as error2:
         print("Error consumed",error,error2)
