#To unpack several variables in a tuple
t = 1,2,3,4,5,6,7
a,b,c,d,e,f,g=t
print(a,g)

#to add an item in a tuple
l = list(t)
print(l)
a = int(input())
l.append(a)
print(l)
t = tuple(l)
print(t)

#to convert tuple into a string
def tupple (a,b,c,d):
                      H=a
                      e=b
                      l=c
                      o=d
                      t1 = (H,e,H,l,o)
                      print(t1)

print(tupple(1,3,2,3))
