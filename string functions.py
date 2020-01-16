s = "Hellomynameisadityagargthismysixthclassofcorepythontodaywearelearningaboutstring"
d = "hgj fjl lf"
g = "jgj"
f = "        "
h =" Hello Python"
q = "25112006"
print(s.istitle()) 
print(s.isalpha()) 
print(s.isalnum()) 
print(f.isspace()) 
print(q.isdigit())
print(h.split())
#print(s.lower())  
#print(s.upper())
h = s+d+g
print(h)                                     
print("".join([s,d,g]))
print("**".join([" ",s,d,g," "]))
print(g.split("j"))
st = 'Hello'
print(st.ljust(10,"o"))
print(st.center(15,"*"))
print(st.rjust(15," "))
#            .rjust
#            .center
print(st[0:4])
print(st[:0:-1])
#------------------
print(len(s))
print(s[1:79])
sti="Hello"
print(sti[1:4])
