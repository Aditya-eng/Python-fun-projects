l = [1,3,2,4,6,75,"String",54,78,93,'Hello','Python',True,False]
print(l)
l1=[]
l2=[]
for i in l:
        if type(i) is int:
                              l1.append(i)
        elif type(i) is str:
                            l2.append(i)
        else:
                 print("Boolean value observed =",i)

l2.sort(key=str.lower)
l1.sort()
l1.extend(l2)
print(l1)
