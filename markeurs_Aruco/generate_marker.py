import cv2
import matplotlib.pyplot as plt

dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
aruco_dict = cv2.aruco.DICT_6X6_250
marker_id = 1     
marker_size = 200  

marker_image = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_size)

plt.imshow(marker_image)
plt.axis('off')
plt.show()


