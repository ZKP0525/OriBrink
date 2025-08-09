# import yinhedata as yh

# df = yh.history_stock_data("SH.600000", "2025-01-07", "2025-01-07", "1min")
# print(df)

import math
import numpy as np

def euclidean_distance(p1, p2):
    """计算两点之间的欧几里得距离"""
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

def frechet_distance(P, Q):
    """弗雷歇距离的迭代实现"""
    n = len(P)
    m = len(Q)
    
    # 初始化距离矩阵
    distance_matrix = np.zeros((n, m))
    
    # 填充第一个元素
    distance_matrix[0, 0] = euclidean_distance(P[0], Q[0])
    
    # 填充第一列
    for i in range(1, n):
        distance_matrix[i, 0] = max(distance_matrix[i-1, 0], euclidean_distance(P[i], Q[0]))
    
    # 填充第一行
    for j in range(1, m):
        distance_matrix[0, j] = max(distance_matrix[0, j-1], euclidean_distance(P[0], Q[j]))
    
    # 填充剩余矩阵
    for i in range(1, n):
        for j in range(1, m):
            distance_matrix[i, j] = max(
                min(distance_matrix[i-1, j], distance_matrix[i-1, j-1], distance_matrix[i, j-1]),
                euclidean_distance(P[i], Q[j])
            )
    
    return distance_matrix[n-1, m-1]

# 测试样例1: 两条相同的直线
P1 = [(0, 0), (1, 1), (2, 2), (3, 3)]
Q1 = [(0, 0), (1, 1), (2, 2), (3, 3)]
print("测试1 - 相同直线:", frechet_distance(P1, Q1))  # 应该为0

# 测试样例2: 两条平行直线
P2 = [(0, 0), (1, 0), (2, 0), (3, 0)]
Q2 = [(0, 1), (1, 1), (2, 1), (3, 1)]
print("测试2 - 平行直线:", frechet_distance(P2, Q2))  # 应该为1

# 测试样例3: 一条直线和一条折线
P3 = [(0, 0), (1, 1), (2, 2), (3, 3)]
Q3 = [(0, 0), (1, 0), (2, 3), (3, 3)]
print("测试3 - 直线和折线:", frechet_distance(P3, Q3))  # 应该约为1.414

# 测试样例4: 两条不同的曲线
P4 = [(0, 0), (1, 1), (2, 1), (3, 0)]
Q4 = [(0, 1), (1, 0), (2, 0), (3, 1)]
print("测试4 - 不同曲线:", frechet_distance(P4, Q4))  # 应该约为1.414

# 测试样例5: 不同长度的曲线
P5 = [(0, 0), (1, 1), (3, 1), (5, 0)]
Q5 = [(0, 0), (2, 1), (5, 0)]
print("测试5 - 不同长度曲线:", frechet_distance(P5, Q5))  # 应该为0

import matplotlib.pyplot as plt

def plot_curves(P, Q, title=""):
    """绘制两条曲线"""
    plt.figure(figsize=(8, 6))
    plt.plot([p[0] for p in P], [p[1] for p in P], 'b-o', label='曲线P')
    plt.plot([q[0] for q in Q], [q[1] for q in Q], 'r-s', label='曲线Q')
    plt.title(f"{title}\n弗雷歇距离: {frechet_distance(P, Q):.3f}")
    plt.legend()
    plt.grid()
    plt.show()

# 可视化测试样例3
plot_curves(P3, Q3, "直线和折线")